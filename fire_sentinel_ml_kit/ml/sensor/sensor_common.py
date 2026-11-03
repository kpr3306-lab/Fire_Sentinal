"""
sensor_common.py — Fire Sentinel sensor model: shared definitions and feature extraction.

!! The feature math here MUST match the firmware (window.cpp + sensor_ml.cpp). ml/sensor/tests/test_parity.py
!! checks the constants against config.h and the model output against the real firmware code.

Pipeline
--------
firmware CSV (1 Hz) --> 30-sample windows --> 16 baseline-relative features --+--> RandomForest (class)
                                                                                +--> IsolationForest (normal-only anomaly score)
Baseline calibration (stage 1, NOT ML) happens on the device (sensors.cpp); every CSV row carries the baseline
that was active, so features are relative to the baseline: a different room / sensor unit / day does not
shift the feature values.
"""
import glob
import json
import os

import numpy as np
import pandas as pd

# ---- mirrored from firmware/config.h (checked by tests/test_parity.py) ----
WINDOW_SIZE = 30
SAMPLE_INTERVAL_S = 1.0
MQ_MIN_BASELINE_RAW = 100.0
UV_FULL_SCALE_COUNTS = 2400.0

CLASS_NAMES = ["NORMAL", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"]
LABEL_TO_ID = {n: i for i, n in enumerate(CLASS_NAMES)}

# window channel order == firmware WindowChannel enum
CHANNELS = ["temp", "mq2", "mq7", "mq135", "uv", "flame"]

FEATURE_NAMES = [
    "temp_dev_c", "temp_std_c", "temp_slope_c_per_min",
    "mq2_rel_mean", "mq2_rel_std", "mq2_rel_slope_per_min",
    "mq7_rel_mean", "mq7_rel_std", "mq7_rel_slope_per_min",
    "mq135_rel_mean", "mq135_rel_std", "mq135_rel_slope_per_min",
    "uv_dev_norm", "uv_std_norm", "uv_slope_norm_per_min",
    "flame_duty",
]
N_FEATURES = len(FEATURE_NAMES)

CSV_COLUMNS = ["ms", "temp", "hum", "pres", "mq2", "mq7", "mq135", "uv", "flame", "valid", "state", "risk",
               "b_temp", "b_mq2", "b_mq7", "b_mq135", "b_uv", "b_ready"]


# ---------------------------------------------------------------------------------------------
# Session files
# ---------------------------------------------------------------------------------------------
def load_session(path):
    """Returns (meta dict, DataFrame). Header comment lines look like '# label=NORMAL'."""
    meta = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            if "=" in line:
                k, v = line[1:].strip().split("=", 1)
                meta[k.strip()] = v.strip()
    df = pd.read_csv(path, comment="#")
    missing = [c for c in CSV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    meta.setdefault("label", os.path.basename(path).split("__")[0])
    return meta, df


# ---------------------------------------------------------------------------------------------
# Window statistics — identical algorithm to firmware window.cpp (population std, least-squares slope)
# ---------------------------------------------------------------------------------------------
def window_stats(block):
    """block: array (WINDOW_SIZE, 6) in CHANNELS order -> mean, std, slope_per_s (each shape (6,))."""
    n = block.shape[0]
    x = np.arange(n, dtype=np.float64)
    mean = block.mean(axis=0)
    std = block.std(axis=0)                      # population std (divide by n), like window.cpp
    sx, sxx = x.sum(), (x * x).sum()
    denom = n * sxx - sx * sx
    sxy = (x[:, None] * block).sum(axis=0)
    slope = ((n * sxy - sx * block.sum(axis=0)) / denom) / SAMPLE_INTERVAL_S
    return mean, std, slope


def features_from_stats(mean, std, slope, b_temp, b_mq2, b_mq7, b_mq135, b_uv):
    """16 baseline-relative features from window stats + the baseline active at the window end."""
    f = np.zeros(N_FEATURES, dtype=np.float64)
    T, M2, M7, M135, UV, FL = range(6)
    f[0] = mean[T] - b_temp
    f[1] = std[T]
    f[2] = slope[T] * 60.0
    for k, (ch, b) in enumerate([(M2, b_mq2), (M7, b_mq7), (M135, b_mq135)]):
        b = max(b, MQ_MIN_BASELINE_RAW)
        f[3 + 3 * k] = mean[ch] / b - 1.0
        f[4 + 3 * k] = std[ch] / b
        f[5 + 3 * k] = slope[ch] * 60.0 / b
    f[12] = (mean[UV] - b_uv) / UV_FULL_SCALE_COUNTS
    f[13] = std[UV] / UV_FULL_SCALE_COUNTS
    f[14] = slope[UV] * 60.0 / UV_FULL_SCALE_COUNTS
    f[15] = mean[FL]
    return f


def iter_windows(df, stride=5):
    """Yield (end_row_index, feature_vector) for every usable window of WINDOW_SIZE consecutive samples.
    Usable = all rows valid, ~1 s apart (no gaps), baseline ready at the window end."""
    ms = df["ms"].to_numpy(dtype=np.float64)
    valid = df["valid"].to_numpy() == 1
    ready = df["b_ready"].to_numpy() == 1
    cols = np.column_stack([df["temp"], df["mq2"], df["mq7"], df["mq135"], df["uv"], df["flame"]]).astype(np.float64)
    dt = np.diff(ms, prepend=ms[0] - 1000.0) / 1000.0
    good_step = (dt > 0.5) & (dt < 1.6)
    last_emit = -10**9
    for end in range(WINDOW_SIZE - 1, len(df)):
        lo = end - WINDOW_SIZE + 1
        if not (valid[lo:end + 1].all() and good_step[lo + 1:end + 1].all() and ready[end]):
            continue
        if end - last_emit < stride:
            continue
        last_emit = end
        mean, std, slope = window_stats(cols[lo:end + 1])
        r = df.iloc[end]
        yield end, features_from_stats(mean, std, slope, r["b_temp"], r["b_mq2"], r["b_mq7"], r["b_mq135"], r["b_uv"])


def build_dataset(root, stride=5):
    """Loads every *.csv under root. Returns X, y, groups (session names), info dict."""
    files = sorted(glob.glob(os.path.join(root, "*.csv")))
    if not files:
        raise SystemExit(f"No session CSV files found in {root}")
    X, y, groups = [], [], []
    sessions, synthetic = {}, False
    for path in files:
        meta, df = load_session(path)
        label = meta["label"].upper()
        if label not in LABEL_TO_ID:
            print(f"  skipping {os.path.basename(path)}: unknown label '{label}'")
            continue
        if meta.get("synthetic", "").lower() == "true":
            synthetic = True
        name = os.path.basename(path)
        n = 0
        for _, feat in iter_windows(df, stride):
            X.append(feat); y.append(LABEL_TO_ID[label]); groups.append(name); n += 1
        sessions[name] = {"label": label, "rows": int(len(df)), "windows": n, "scenario": meta.get("scenario", "")}
    if not X:
        raise SystemExit("No usable windows. Sessions need >= 30 s of rows with b_ready=1 (baseline + MQ warm-up done).")
    return np.array(X), np.array(y), np.array(groups), {"sessions": sessions, "synthetic": synthetic, "files": len(files)}


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
