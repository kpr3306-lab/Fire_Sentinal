"""
ml/sensor/export_c.py — turn the trained RandomForest + IsolationForest into a C header for the ESP32-S3.

    python ml/sensor/export_c.py                                  # reads ml/sensor/artifacts, writes ml/sensor/firmware_src/sensor_model.h
    python ml/sensor/export_c.py --firmware-dir "C:\\path\\to\\esp32s3_cam_main"   # also copies the header into the sketch folder

The header is compiled into the firmware (flash) — no SD card needed. Trees are flattened into const arrays;
inference code is firmware_src/sensor_ml.cpp. ml/sensor/tests/test_parity.py proves the C code reproduces scikit-learn.
"""
import argparse
import math
import os
import shutil
import sys

import joblib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sensor_common as sc
import json


def avg_path_length(n):
    """c(n) from the Isolation Forest paper (same as sklearn's _average_path_length)."""
    if n <= 1: return 0.0
    if n == 2: return 1.0
    return 2.0 * (math.log(n - 1.0) + 0.5772156649015329) - 2.0 * (n - 1.0) / n


def flatten_rf(rf):
    feat, thr, left, right, roots, leaves = [], [], [], [], [], []
    for est in rf.estimators_:
        t = est.tree_
        base = len(feat)
        roots.append(base)
        for i in range(t.node_count):
            if t.children_left[i] == -1:                        # leaf
                v = t.value[i, 0, :].astype(np.float64)
                v = v / v.sum()
                feat.append(-1); thr.append(0.0)
                left.append(len(leaves)); right.append(-1)
                leaves.append([int(round(x * 255)) for x in v])
            else:
                feat.append(int(t.feature[i])); thr.append(float(t.threshold[i]))
                left.append(base + int(t.children_left[i])); right.append(base + int(t.children_right[i]))
    return feat, thr, left, right, roots, leaves


def flatten_if(model):
    feat, thr, left, right, roots = [], [], [], [], []
    for est, fidx in zip(model.estimators_, model.estimators_features_):
        if len(fidx) != sc.N_FEATURES or not np.array_equal(np.sort(fidx), np.arange(sc.N_FEATURES)):
            raise SystemExit("IsolationForest used a feature subset (max_features < 1.0); not supported by the exporter.")
        t = est.tree_
        base = len(feat)
        roots.append(base)
        depth = np.zeros(t.node_count, dtype=np.int64)
        for i in range(t.node_count):                           # children always have larger indices than parents
            if t.children_left[i] != -1:
                depth[t.children_left[i]] = depth[i] + 1
                depth[t.children_right[i]] = depth[i] + 1
        for i in range(t.node_count):
            if t.children_left[i] == -1:                        # leaf: store h = depth + c(n_node_samples)
                feat.append(-1)
                thr.append(float(depth[i] + avg_path_length(int(t.n_node_samples[i]))))
                left.append(-1); right.append(-1)
            else:
                feat.append(int(t.feature[i])); thr.append(float(t.threshold[i]))
                left.append(base + int(t.children_left[i])); right.append(base + int(t.children_right[i]))
    return feat, thr, left, right, roots


def cf(x):
    """C float literal: always has a '.' or exponent ('4' -> '4.0f'), never a bare '4f'."""
    s = "%.9g" % x
    if not any(ch in s for ch in ".en"):
        s += ".0"
    return s + "f"


def arr(name, ctype, values, fmt="{}", per_line=12):
    out = [f"static const {ctype} {name}[{len(values)}] = {{"]
    for i in range(0, len(values), per_line):
        out.append("  " + ", ".join((cf(v) if fmt == "F" else fmt.format(v)) for v in values[i:i + per_line]) + ",")
    out.append("};")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=os.path.join("ml", "sensor", "artifacts"))
    ap.add_argument("--out", default=os.path.join("ml", "sensor", "firmware_src", "sensor_model.h"))
    ap.add_argument("--firmware-dir", help="optional: also copy sensor_model.h into this sketch folder")
    args = ap.parse_args()

    rf = joblib.load(os.path.join(args.artifacts, "sensor_rf.joblib"))
    iforest = joblib.load(os.path.join(args.artifacts, "sensor_iforest.joblib"))
    with open(os.path.join(args.artifacts, "sensor_model_manifest.json")) as f:
        man = json.load(f)
    if list(rf.classes_) != [0, 1, 2]:
        raise SystemExit(f"Classifier classes are {list(rf.classes_)}; expected [0,1,2] (all three classes need data).")

    rf_feat, rf_thr, rf_l, rf_r, rf_roots, rf_leaves = flatten_rf(rf)
    if_feat, if_thr, if_l, if_r, if_roots = flatten_if(iforest)
    for n, name in ((len(rf_feat), "RF"), (len(if_feat), "IsolationForest")):
        if n >= 32767:
            raise SystemExit(f"{name} has {n} nodes; int16 indices overflow. Train with fewer/shallower trees.")
    c_norm = avg_path_length(int(iforest.max_samples_))
    thr = man["iforest"]["threshold"]
    flash_kb = (len(rf_feat) * 11 + len(rf_leaves) * 3 + len(if_feat) * 11) / 1024

    h = f"""// sensor_model.h — GENERATED by ml/sensor/export_c.py. Do not edit by hand.
// model {man['model_version']} | data: {man['data_dir']} | synthetic: {man['synthetic_data']}
// ~{flash_kb:.0f} KB of const data (lives in flash)
#ifndef SENSOR_MODEL_H
#define SENSOR_MODEL_H
#include <stdint.h>

#define SENSOR_MODEL_PRESENT   1
#define SENSOR_MODEL_SYNTHETIC {1 if man['synthetic_data'] else 0}
#define SENSOR_MODEL_VERSION   "{man['model_version']}"
#define SENSOR_N_FEATURES      {sc.N_FEATURES}
#define SENSOR_N_CLASSES       3
#define SENSOR_WINDOW_SIZE     {man['window_size']}

// Random forest: leaf nodes have FEAT = -1 and LEFT = row in LEAF (class probabilities * 255)
#define SENSOR_RF_N_TREES {len(rf_roots)}
{arr('SENSOR_RF_ROOT', 'int16_t', rf_roots)}
{arr('SENSOR_RF_FEAT', 'int8_t', rf_feat)}
{arr('SENSOR_RF_THR', 'float', rf_thr, 'F')}
{arr('SENSOR_RF_LEFT', 'int16_t', rf_l)}
{arr('SENSOR_RF_RIGHT', 'int16_t', rf_r)}
static const uint8_t SENSOR_RF_LEAF[{len(rf_leaves)}][3] = {{
""" + "\n".join("  {%d,%d,%d}," % tuple(r) for r in rf_leaves) + f"""
}};

// Isolation forest (trained on NORMAL windows only). Leaf THR holds the path length h = depth + c(n_leaf).
// score s = 2^(-mean(h)/SENSOR_IF_C) in (0,1); s > SENSOR_IF_THRESHOLD  => "not normal"
#define SENSOR_IF_N_TREES {len(if_roots)}
#define SENSOR_IF_C {cf(c_norm)}
#define SENSOR_IF_THRESHOLD {cf(thr)}
{arr('SENSOR_IF_ROOT', 'int16_t', if_roots)}
{arr('SENSOR_IF_FEAT', 'int8_t', if_feat)}
{arr('SENSOR_IF_THR', 'float', if_thr, 'F')}
{arr('SENSOR_IF_LEFT', 'int16_t', if_l)}
{arr('SENSOR_IF_RIGHT', 'int16_t', if_r)}

#endif
"""
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(h)
    print(f"Wrote {args.out}: RF {len(rf_roots)} trees / {len(rf_feat)} nodes, IF {len(if_roots)} trees / {len(if_feat)} nodes (~{flash_kb:.0f} KB flash)")
    if man["synthetic_data"]:
        print("  *** this model was trained on SYNTHETIC data — for pipeline testing only, do not rely on it ***")
    if args.firmware_dir:
        shutil.copy(args.out, os.path.join(args.firmware_dir, "sensor_model.h"))
        print(f"Copied into {args.firmware_dir}")
    else:
        print("Next: copy firmware_src/sensor_model.h into your esp32s3_cam_main sketch folder (replacing the stub), recompile, flash.")


if __name__ == "__main__":
    main()
