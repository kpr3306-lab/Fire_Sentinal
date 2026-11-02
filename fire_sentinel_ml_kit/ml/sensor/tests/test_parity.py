"""
Proves the firmware code reproduces scikit-learn and the Python feature math.

  1. checks sensor_common.py constants against the firmware's config.h
  2. trains a small model on the SYNTHETIC demo sessions, exports sensor_model.h
  3. compiles the REAL firmware sensor_ml.cpp (+ window.h/sensors.h/config.h) on the PC with g++
  4. feeds the same window statistics to both and compares features, class probabilities and anomaly scores

Needs g++ and the firmware sketch folder:
    set FIRMWARE_DIR=C:\\path\\to\\esp32s3_cam_main     (PowerShell: $env:FIRMWARE_DIR="...")
    python -m unittest ml/sensor/tests/test_parity.py -v
Skipped automatically if either is missing.
"""
import os, re, shutil, subprocess, sys, tempfile, unittest
import numpy as np
import joblib

HERE = os.path.dirname(os.path.abspath(__file__))
SENSOR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(SENSOR))
sys.path.insert(0, SENSOR)
import sensor_common as sc

FW = os.environ.get("FIRMWARE_DIR", "")


def cfg_value(name):
    txt = open(os.path.join(FW, "config.h"), encoding="utf-8").read()
    m = re.search(r"#define\s+" + name + r"\s+([0-9.]+)", txt)
    return float(m.group(1))


@unittest.skipUnless(shutil.which("g++") and FW and os.path.exists(os.path.join(FW, "sensor_ml.cpp")),
                     "needs g++ and FIRMWARE_DIR pointing at the sketch folder")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        art = os.path.join(cls.tmp, "art")
        env = dict(os.environ)
        demo = os.path.join(SENSOR, "dataset", "demo_synthetic")
        if not os.path.isdir(demo) or not os.listdir(demo):
            subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "make_demo_data.py")], cwd=ROOT)
        subprocess.check_call([sys.executable, os.path.join(SENSOR, "train_sensor.py"), "--data", demo, "--out", art], cwd=ROOT, stdout=subprocess.DEVNULL)
        build = os.path.join(cls.tmp, "build"); os.makedirs(build)
        subprocess.check_call([sys.executable, os.path.join(SENSOR, "export_c.py"), "--artifacts", art, "--out", os.path.join(build, "sensor_model.h")], cwd=ROOT, stdout=subprocess.DEVNULL)
        for f in ["sensor_ml.cpp", "sensor_ml.h", "window.h", "window.cpp", "sensors.h", "config.h"]:
            shutil.copy(os.path.join(FW, f), build)
        for f in ["Arduino.h", "secrets.h"]:
            shutil.copy(os.path.join(HERE, "host_stubs", f), build)
        shutil.copy(os.path.join(HERE, "parity_harness.cpp"), build)
        exe = os.path.join(build, "harness")
        subprocess.check_call(["g++", "-std=c++17", "-O1", "-I", build, os.path.join(build, "parity_harness.cpp"),
                               os.path.join(build, "sensor_ml.cpp"), os.path.join(build, "window.cpp"), "-o", exe])
        cls.exe = exe
        cls.rf = joblib.load(os.path.join(art, "sensor_rf.joblib"))
        cls.iforest = joblib.load(os.path.join(art, "sensor_iforest.joblib"))
        import json
        cls.thr = json.load(open(os.path.join(art, "sensor_model_manifest.json")))["iforest"]["threshold"]
        cls.demo = demo

    def test_constants_match_config_h(self):
        self.assertEqual(sc.WINDOW_SIZE, int(cfg_value("WINDOW_SIZE")))
        self.assertAlmostEqual(sc.SAMPLE_INTERVAL_S * 1000, cfg_value("SENSOR_SAMPLE_INTERVAL_MS"))
        self.assertAlmostEqual(sc.MQ_MIN_BASELINE_RAW, cfg_value("MQ_MIN_BASELINE_RAW"))
        self.assertAlmostEqual(sc.UV_FULL_SCALE_COUNTS, cfg_value("UV_FULL_SCALE_COUNTS"))

    def test_firmware_matches_sklearn(self):
        import glob
        rows_in, py_feat, py_p, py_s = [], [], [], []
        for path in sorted(glob.glob(os.path.join(self.demo, "*.csv"))):
            meta, df = sc.load_session(path)
            cols = np.column_stack([df["temp"], df["mq2"], df["mq7"], df["mq135"], df["uv"], df["flame"]]).astype(np.float64)
            for end, feat in sc.iter_windows(df, stride=7):
                mean, std, slope = sc.window_stats(cols[end - sc.WINDOW_SIZE + 1:end + 1])
                r = df.iloc[end]
                rows_in.append(np.r_[mean, std, slope, r["b_temp"], r["b_mq2"], r["b_mq7"], r["b_mq135"], r["b_uv"]])
                py_feat.append(feat)
        X = np.array(py_feat).astype(np.float32)
        py_p = self.rf.predict_proba(X)
        py_s = -self.iforest.score_samples(X)
        inp = "\n".join(" ".join(f"{v:.12g}" for v in r) for r in rows_in) + "\n"
        out = subprocess.run([self.exe], input=inp, capture_output=True, text=True, check=True).stdout.strip().splitlines()
        self.assertEqual(len(out), len(rows_in))
        c = np.array([[float(x) for x in line.split()] for line in out])
        c_feat, c_p, c_s, c_flag = c[:, :16], c[:, 16:19], c[:, 19], c[:, 20]
        print(f"\n  {len(out)} windows compared")
        # features: float32 firmware math vs float64 Python
        rel = np.abs(c_feat - np.array(py_feat)) / (1e-3 + np.abs(np.array(py_feat)))
        print(f"  feature max relative diff   {rel.max():.2e}")
        self.assertLess(rel.max(), 1e-3)
        # class decision agreement + probability agreement
        agree = np.mean(c_p.argmax(axis=1) == py_p.argmax(axis=1))
        print(f"  class agreement             {agree:.4f}   max |dp| {np.abs(c_p - py_p).max():.4f}")
        self.assertGreaterEqual(agree, 0.995)
        self.assertLess(np.median(np.abs(c_p - py_p)), 0.01)
        # anomaly score + flag
        print(f"  anomaly score max |ds|      {np.abs(c_s - py_s).max():.4f}")
        self.assertLess(np.median(np.abs(c_s - py_s)), 0.005)
        flag_agree = np.mean(c_flag == (py_s > self.thr))
        print(f"  anomaly flag agreement      {flag_agree:.4f}")
        self.assertGreaterEqual(flag_agree, 0.99)


if __name__ == "__main__":
    unittest.main(verbosity=2)
