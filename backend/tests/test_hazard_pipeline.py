"""
Run from the backend folder:   python -m unittest tests.test_hazard_pipeline -v
Uses a throwaway database and fake detections — needs neither the YOLO weights nor ultralytics.
"""
import io, json, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from services import hazard_service, yolo_service
from services.yolo_service import DetectionResult

DET = lambda n, a: DetectionResult("ok", n, a, [[0.1, 0.1, 0.2, 0.2, 0.9]] * n)
OFF = DetectionResult("unavailable")


class HazardLogic(unittest.TestCase):
    def test_cases(self):
        c = config
        cases = [
            ("HAZARDOUS_FIRE", OFF, None, "HAZARDOUS"),                       # CNN alone is enough
            ("CONTROLLED_FLAME", DET(1, c.HAZARD_AREA_RATIO + .05), None, "HAZARDOUS"),   # big flame overrides CNN
            ("CONTROLLED_FLAME", DET(1, .02), .01, "HAZARDOUS"),              # grew 2x, above min area
            ("CONTROLLED_FLAME", DET(1, .02), .018, "CONTROLLED"),            # barely grew
            ("CONTROLLED_FLAME", DET(1, .005), .001, "CONTROLLED"),           # grew 5x but below min area -> ignored
            ("CONTROLLED_FLAME", DET(0, 0), None, "CONTROLLED"),              # detector missed it; CNN still says flame
            ("NO_FLAME", DET(1, .02), None, "CONTROLLED"),                    # disagreement -> flame evidence wins
            ("NO_FLAME", DET(0, 0), None, "NONE"),
            ("NO_FLAME", OFF, None, "NONE"),
            ("PENDING_MODEL", DET(0, 0), None, "UNKNOWN"),                    # nothing found != no fire
            ("PENDING_MODEL", OFF, None, "UNKNOWN"),
            ("PENDING_MODEL", DET(1, .03), None, "CONTROLLED"),
            ("PENDING_MODEL", DET(1, c.HAZARD_AREA_RATIO), None, "HAZARDOUS"),
            ("NO_FLAME", DetectionResult("error"), None, "NONE"),
        ]
        for cnn, det, prev, want in cases:
            got = hazard_service.assess(cnn, det, prev)
            self.assertEqual(got.level, want, (cnn, det, prev, got))
            self.assertTrue(got.reasons)

    def test_growth_needs_positive_previous(self):
        a = hazard_service.assess("CONTROLLED_FLAME", DET(1, .05), 0.0)
        self.assertIsNone(a.growth); self.assertEqual(a.level, "CONTROLLED")


class YoloService(unittest.TestCase):
    def test_union_area_not_double_counted(self):
        self.assertAlmostEqual(yolo_service.union_area([[0, 0, .5, .5, .9], [0, 0, .5, .5, .8]]), .25, places=2)
        self.assertAlmostEqual(yolo_service.union_area([[0, 0, .5, 1, .9], [.5, 0, 1, 1, .9]]), 1.0, places=2)
        self.assertEqual(yolo_service.union_area([]), 0.0)

    def test_missing_weights_is_unavailable(self):
        old = config.YOLO_MODEL_PATH
        config.YOLO_MODEL_PATH = "/nonexistent/fire_yolo.pt"; yolo_service._state.update(model=None, mtime=None)
        try:
            self.assertEqual(yolo_service.detect_flames("x.jpg").status, "unavailable")
        finally:
            config.YOLO_MODEL_PATH = old

    def test_stuck_warm_up_does_not_hang_uploads(self):
        yolo_service._lock.acquire()                  # a warm-up that never finishes
        try:
            self.assertEqual(yolo_service.detect_flames("x.jpg").status, "unavailable")
        finally:
            yolo_service._lock.release()

    def test_parses_ultralytics_result_shape(self):
        class T(list):
            def tolist(self): return list(self)
        class Boxes:
            xyxyn = T([[.1, .1, .3, .3], [.2, .2, .4, .4]]); conf = T([.9, .5])
            def __len__(self): return 2
        class Res: boxes = Boxes()
        class Model:
            def predict(self, *a, **k): return [Res()]
        orig = yolo_service._load; yolo_service._load = lambda: Model()
        try:
            r = yolo_service.detect_flames("x.jpg")
        finally:
            yolo_service._load = orig
        self.assertEqual((r.status, r.n_flames), ("ok", 2)); self.assertGreater(r.area_ratio, .04)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config.DATABASE_PATH = os.path.join(self.tmp.name, "t.db")
        config.SNAPSHOT_STORAGE_DIR = os.path.join(self.tmp.name, "snaps")
        yolo_service._state.update(model=None, mtime=None)
        import app as app_module
        self.client = app_module.create_app().test_client()
        c = sqlite3.connect(config.DATABASE_PATH); c.execute("INSERT INTO devices (device_id) VALUES ('dev1')"); c.commit(); c.close()
        from PIL import Image
        b = io.BytesIO(); Image.new("RGB", (64, 48), (200, 80, 20)).save(b, "JPEG"); self.jpg = b.getvalue()

    def tearDown(self): self.tmp.cleanup()

    def post(self, reason="confirming"):
        return self.client.post("/api/camera/snapshot", data={"device_id": "dev1", "reason": reason,
                                "image": (io.BytesIO(self.jpg), "s.jpg")}, content_type="multipart/form-data")

    def rows(self):
        c = sqlite3.connect(config.DATABASE_PATH); c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM snapshots ORDER BY id").fetchall(); c.close(); return r

    def test_detector_off_still_saves(self):
        config.YOLO_MODEL_PATH = "/nonexistent/fire_yolo.pt"
        r = self.post(); self.assertEqual(r.status_code, 200)
        body = r.get_json(); self.assertEqual(body["detector_status"], "unavailable")
        row = self.rows()[0]
        self.assertEqual(row["detector_status"], "unavailable"); self.assertIsNone(row["flame_area_ratio"])
        self.assertIsNone(row["flame_boxes"]); self.assertEqual(row["hazard_level"], "UNKNOWN")

    def test_device_vision_result_used_when_backend_models_off(self):
        config.YOLO_MODEL_PATH = "/nonexistent/fire_yolo.pt"
        r = self.client.post("/api/camera/snapshot", data={
            "device_id": "dev1", "reason": "FIRE_CONFIRMED", "cnn_class": "HAZARDOUS_FIRE", "cnn_conf": "0.91",
            "yolo_boxes": "[[0.1,0.2,0.5,0.6,0.8]]", "image": (io.BytesIO(self.jpg), "s.jpg")},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        row = self.rows()[0]
        self.assertEqual((row["classification"], row["detector_status"], row["flame_count"]), ("HAZARDOUS_FIRE", "ok", 1))
        self.assertAlmostEqual(row["confidence"], 0.91); self.assertEqual(row["hazard_level"], "HAZARDOUS")
        self.assertEqual(yolo_service.from_device_boxes("not json").status, "error")

    def test_growth_between_two_snapshots(self):
        seq = iter([DET(1, .02), DET(1, .06)])
        orig = yolo_service.detect_flames; yolo_service.detect_flames = lambda p: next(seq)
        try:
            self.post(); r2 = self.post()
        finally:
            yolo_service.detect_flames = orig
        a, b = self.rows()
        self.assertEqual(a["hazard_level"], "CONTROLLED"); self.assertIsNone(a["flame_growth"])
        self.assertEqual(b["hazard_level"], "HAZARDOUS"); self.assertAlmostEqual(b["flame_growth"], 3.0, places=1)
        self.assertEqual(r2.get_json()["hazard_level"], "HAZARDOUS")
        self.assertIn("grew", " ".join(json.loads(b["hazard_reasons"])))
        self.assertEqual(len(json.loads(b["flame_boxes"])), 1)
        listed = self.client.get("/api/camera/snapshots?device_id=dev1").get_json()
        self.assertEqual({x["hazard_level"] for x in listed}, {"CONTROLLED", "HAZARDOUS"})

    def test_snapshot_recorded_even_if_detector_blows_up(self):
        def boom(p): raise RuntimeError("model stuck")
        orig = yolo_service.detect_flames; yolo_service.detect_flames = boom
        self.client.application.config["PROPAGATE_EXCEPTIONS"] = False     # get the 500 instead of the raise
        try:
            self.assertEqual(self.post().status_code, 500)
        finally:
            yolo_service.detect_flames = orig
        row = self.rows()[0]
        self.assertEqual((row["classification"], row["detector_status"]), ("PENDING_MODEL", "pending"))
        self.assertEqual(len(self.client.get("/api/camera/snapshots?device_id=dev1").get_json()), 1)

    def test_device_result_kept_if_backend_models_hang(self):
        from services import ml_inference_service as ml
        def boom(p): raise RuntimeError("model stuck")
        orig_d, orig_c = yolo_service.detect_flames, ml.classify_snapshot
        yolo_service.detect_flames = boom
        ml.classify_snapshot = lambda p: ml.ClassificationResult("PENDING_MODEL", 0.0)
        self.client.application.config["PROPAGATE_EXCEPTIONS"] = False
        try:
            self.client.post("/api/camera/snapshot", data={"device_id": "dev1", "reason": "on_demand",
                             "cnn_class": "NO_FLAME", "cnn_conf": "0.97", "image": (io.BytesIO(self.jpg), "s.jpg")},
                             content_type="multipart/form-data")
        finally:
            yolo_service.detect_flames, ml.classify_snapshot = orig_d, orig_c
        row = self.rows()[0]
        self.assertEqual((row["classification"], row["detector_status"]), ("NO_FLAME", "pending"))
        self.assertAlmostEqual(row["confidence"], 0.97)

    def test_old_snapshots_not_used_for_growth(self):
        orig = yolo_service.detect_flames; yolo_service.detect_flames = lambda p: DET(1, .02)
        try:
            self.post()
            c = sqlite3.connect(config.DATABASE_PATH)
            c.execute("UPDATE snapshots SET created_at = datetime('now', '-1 hour')"); c.commit(); c.close()
            yolo_service.detect_flames = lambda p: DET(1, .06); self.post()
        finally:
            yolo_service.detect_flames = orig
        self.assertIsNone(self.rows()[1]["flame_growth"])      # previous one is outside the window


class Migration(unittest.TestCase):
    def test_old_database_gets_new_columns_and_keeps_rows(self):
        import db
        with tempfile.TemporaryDirectory() as t:
            config.DATABASE_PATH = os.path.join(t, "old.db"); config.SNAPSHOT_STORAGE_DIR = os.path.join(t, "s")
            c = sqlite3.connect(config.DATABASE_PATH)
            c.executescript("""CREATE TABLE devices (device_id TEXT PRIMARY KEY);
              CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, room_id INTEGER, reason TEXT,
                file_path TEXT NOT NULL, classification TEXT DEFAULT 'PENDING_MODEL', confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
              INSERT INTO snapshots (device_id, file_path) VALUES ('d', '/old/one.jpg');""")
            c.commit(); c.close()
            db.init_db(); db.init_db()                                   # twice: must be idempotent
            c = sqlite3.connect(config.DATABASE_PATH)
            cols = {r[1] for r in c.execute("PRAGMA table_info(snapshots)")}
            self.assertTrue(set(db.SNAPSHOT_EXTRA_COLUMNS) <= cols)
            self.assertEqual(c.execute("SELECT file_path, hazard_level FROM snapshots").fetchone(), ("/old/one.jpg", None))
            c.close()


if __name__ == "__main__":
    unittest.main()
