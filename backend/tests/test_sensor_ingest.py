"""
End-to-end test of POST /api/sensor-data with the v2 firmware payload and the simulated dispatch.
Uses a temp database and fake Telegram/email senders — nothing leaves the machine.
"""
import os, sys, tempfile, unittest, json, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

_tmp = tempfile.mkdtemp()
config.DATABASE_PATH = os.path.join(_tmp, "t.db")
config.SNAPSHOT_STORAGE_DIR = os.path.join(_tmp, "snaps")
config.DEBUG = False
config.DISPATCH_COUNTDOWN_S = 30

from services import telegram_service, email_service, dispatch_service
import app as app_module


class Clock:
    def __init__(self): self.t = 5000.0
    def __call__(self): return self.t
    def adv(self, s): self.t += s


def payload(state, risk=50, ack_seq=0, **extra):
    p = {"device_id": "fs-TEST", "timestamp_ms": 1000, "state": state, "risk_score": risk,
         "buzzer_silenced": False, "sensor_fault": False, "ack_seq": ack_seq,
         "sensors": {"temperature_c": 30.5, "humidity_pct": 40, "pressure_hpa": 1000,
                     "mq2_ppm": 120, "mq7_ppm": 20, "mq135_ppm": 30, "uv_index": 0.1,
                     "mq2_raw": 12000, "mq7_raw": 5000, "mq135_raw": 6000, "uv_raw": 40,
                     "flame_detected": state == "FIRE_CONFIRMED", "reading_valid": True},
         "fusion": {"temp_deviation": 1.2, "gas_deviation_pct": 80, "temp_rate_c_per_min": 2.5, "gas_agree_count": 2},
         "power": {"valid": True, "battery_pct": -1, "bus_v": 5.0, "current_ma": 450, "power_mw": 2250, "battery_v": 0},
         "window": {"temp": {"mean": 30, "std": 0.1, "slope_per_s": 0.01}},
         "ml": {"class": "NORMAL", "conf": 0.9, "anomaly": 0.4, "anomalous": False}}
    p.update(extra)
    return p


class IngestTests(unittest.TestCase):
    def setUp(self):
        # other test modules also point config at their own temp DB at import time — claim ours for each test
        os.makedirs(_tmp, exist_ok=True)
        config.DATABASE_PATH = os.path.join(_tmp, "t.db")
        config.SNAPSHOT_STORAGE_DIR = os.path.join(_tmp, "snaps")
        if os.path.exists(config.DATABASE_PATH): os.remove(config.DATABASE_PATH)
        self.sent = []          # (kind, chat_id, text)
        telegram_service.send_text = lambda m, chat_id=None: (self.sent.append(("text", chat_id, m)) or (True, ""))
        telegram_service.send_photo = lambda c, p, chat_id=None: (self.sent.append(("photo", chat_id, c)) or (True, ""))
        email_service.send_email = lambda s, b, attachment_path=None: (self.sent.append(("email", None, s)) or (True, ""))
        config.TELEGRAM_FIRE_DEPT_SIM_CHAT_ID = "SIMCHAT"
        dispatch_service.reset_service()
        self.clk = Clock()
        dispatch_service.get_service(clock=self.clk)
        self.app = app_module.create_app()
        self.c = self.app.test_client()

    def post(self, p):
        self.clk.adv(1)
        r = self.c.post("/api/sensor-data", json=p)
        self.assertEqual(r.status_code, 200, r.data)
        return r.get_json()

    def db(self):
        import sqlite3
        c = sqlite3.connect(config.DATABASE_PATH); c.row_factory = sqlite3.Row; self.addCleanup(c.close); return c

    def test_unregistered_device_and_v2_columns_are_stored(self):
        out = self.post(payload("NORMAL", 5))
        self.assertEqual(out["status"], "ok")
        row = self.db().execute("SELECT * FROM sensor_readings").fetchone()
        self.assertEqual(row["mq2_raw"], 12000); self.assertEqual(row["current_ma"], 450)
        self.assertEqual(row["ack_seq"], 0); self.assertEqual(row["sensor_fault"], 0)
        self.assertIn("temp", json.loads(row["window_json"])); self.assertEqual(json.loads(row["ml_json"])["class"], "NORMAL")

    def test_old_firmware_payload_still_works(self):
        old = {"device_id": "fs-OLD", "timestamp_ms": 1, "state": "NORMAL", "risk_score": 3,
               "sensors": {"temperature_c": 25, "mq2_ppm": 10, "reading_valid": True}, "fusion": {}}
        self.assertEqual(self.post(old)["status"], "ok")

    def test_alert_policy_unchanged(self):
        self.post(payload("NORMAL", 5))
        self.post(payload("PRECURSOR", 35))
        kinds = [k for k, _, _ in self.sent]
        self.assertEqual(kinds, ["text"])                       # PRECURSOR = Telegram only
        self.post(payload("CONFIRMING", 55))
        self.assertEqual([k for k, _, _ in self.sent], ["text", "text", "email"])

    def test_fire_confirmed_countdown_then_simulated_dispatch(self):
        self.post(payload("CONFIRMING", 55))
        out = self.post(payload("FIRE_CONFIRMED", 80))
        self.assertEqual(out["dispatch_event"], "countdown_started")
        st = self.c.get("/api/dispatch/status?device_id=fs-TEST").get_json()
        self.assertEqual(st["phase"], "pending"); self.assertTrue(st["simulated"])
        for _ in range(29): self.post(payload("FIRE_CONFIRMED", 80))
        self.assertFalse(any(c == "SIMCHAT" for _, c, _ in self.sent))
        out = self.post(payload("FIRE_CONFIRMED", 80)); self.post(payload("FIRE_CONFIRMED", 80))
        dispatched = [m for _, c, m in self.sent if c == "SIMCHAT"]
        self.assertEqual(len(dispatched), 1); self.assertIn("SIMULATION", dispatched[0])
        ev = self.c.get("/api/dispatch/events").get_json()
        self.assertEqual(ev[0]["event_type"], "dispatched_sim")
        tl = self.c.get("/api/events?device_id=fs-TEST").get_json()
        self.assertTrue(any("Dispatch (simulated)" in (e["message"] or "") for e in tl))

    def test_device_button_ack_cancels(self):
        self.post(payload("FIRE_CONFIRMED", 80, ack_seq=0))
        for _ in range(5): self.post(payload("FIRE_CONFIRMED", 80, ack_seq=0))
        out = self.post(payload("FIRE_CONFIRMED", 80, ack_seq=1))
        self.assertEqual(out["dispatch_event"], "cancelled")
        for _ in range(60): self.post(payload("FIRE_CONFIRMED", 80, ack_seq=1))
        self.assertFalse(any(c == "SIMCHAT" for _, c, _ in self.sent))

    def test_dashboard_cancel_route(self):
        self.post(payload("FIRE_CONFIRMED", 80))
        self.assertTrue(self.c.post("/api/dispatch/cancel", json={"device_id": "fs-TEST"}).get_json()["cancelled"])
        self.assertEqual(self.c.get("/api/dispatch/status?device_id=fs-TEST").get_json()["phase"], "cancelled")
        self.assertEqual(self.c.post("/api/dispatch/cancel", json={}).status_code, 400)

    def test_telegram_down_does_not_break_ingestion(self):
        telegram_service.send_text = lambda *a, **k: (False, "Telegram request failed: down")   # what the real service returns
        telegram_service.send_photo = telegram_service.send_text
        self.assertEqual(self.post(payload("FIRE_CONFIRMED", 90))["status"], "ok")
        alerts = self.db().execute("SELECT success FROM alerts WHERE channel = 'telegram'").fetchall()
        self.assertTrue(alerts and all(a["success"] == 0 for a in alerts))   # failure is logged, not raised

    def test_dispatch_can_be_disabled(self):
        config.DISPATCH_ENABLED = False
        try:
            self.assertIsNone(self.post(payload("FIRE_CONFIRMED", 90))["dispatch_event"])
        finally:
            config.DISPATCH_ENABLED = True

    def test_existing_database_is_migrated(self):
        import sqlite3
        if os.path.exists(config.DATABASE_PATH): os.remove(config.DATABASE_PATH)
        c = sqlite3.connect(config.DATABASE_PATH)
        c.executescript("""CREATE TABLE sensor_readings (id INTEGER PRIMARY KEY, device_id TEXT, state TEXT, created_at TIMESTAMP);
                           CREATE TABLE snapshots (id INTEGER PRIMARY KEY, device_id TEXT, file_path TEXT, created_at TIMESTAMP);""")
        c.commit(); c.close()
        import db; db.init_db()
        cols = {r[1] for r in self.db().execute("PRAGMA table_info(sensor_readings)")}
        self.assertTrue({"mq2_raw", "ack_seq", "window_json", "ml_json"} <= cols)


if __name__ == "__main__":
    unittest.main(verbosity=2)
