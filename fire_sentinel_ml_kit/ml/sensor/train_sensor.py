"""
ml/sensor/train_sensor.py — train the Fire Sentinel sensor model (stage 2 + 3 of the sensor ML plan).

  Stage 1  baseline calibration (NOT ML)        -> already on the device (sensors.cpp), logged in every CSV row
  Stage 2  classifier on window features        -> RandomForest: NORMAL / CONTROLLED_FLAME / HAZARDOUS_FIRE
  Stage 3  anomaly detector, NORMAL-only data   -> IsolationForest: "this is not normal", even for fires never recorded

Run from the fire_sentinel_ml_kit folder (PowerShell):
    pip install scikit-learn pandas numpy joblib matplotlib
    python ml/sensor/train_sensor.py
    python ml/sensor/train_sensor.py --data ml/sensor/dataset/demo_synthetic --out ml/sensor/artifacts_demo   # smoke test only

(No TensorFlow involved, so $env:TF_USE_LEGACY_KERAS is not needed here.)

Evaluation is LEAVE-ONE-SESSION-OUT: windows from one recording are never in both train and test (neighbouring
windows overlap by 29/30 samples, a random split would leak and give fantasy accuracy).

Outputs (in --out, default ml/sensor/artifacts):
    sensor_rf.joblib  sensor_iforest.joblib  sensor_model_manifest.json  sensor_report.md  (+ PNG plots)
"""
import argparse
import os
import sys
import time

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import confusion_matrix, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sensor_common as sc


def make_rf(args, seed):
    return RandomForestClassifier(
        n_estimators=args.trees, max_depth=args.max_depth, min_samples_leaf=args.min_leaf,
        class_weight="balanced", random_state=seed, n_jobs=-1)


def make_if(args, seed):
    return IsolationForest(n_estimators=args.if_trees, max_samples=args.if_samples, contamination="auto",
                           random_state=seed, n_jobs=-1)


def iforest_score(model, X):
    """Isolation-forest anomaly score s in (0,1); higher = more anomalous. (= -model.score_samples)"""
    return -model.score_samples(X)


def per_class_report(cm):
    lines = ["| class | precision | recall | support |", "|---|---|---|---|"]
    for i, name in enumerate(sc.CLASS_NAMES):
        tp = cm[i, i]; sup = cm[i].sum(); pred = cm[:, i].sum()
        p = tp / pred if pred else float("nan"); r = tp / sup if sup else float("nan")
        lines.append(f"| {name} | {p:.3f} | {r:.3f} | {int(sup)} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join("ml", "sensor", "dataset", "raw"))
    ap.add_argument("--out", default=os.path.join("ml", "sensor", "artifacts"))
    ap.add_argument("--stride", type=int, default=5, help="samples between windows (5 = 1 window / 5 s)")
    ap.add_argument("--trees", type=int, default=40)
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--min-leaf", type=int, default=5)
    ap.add_argument("--if-trees", type=int, default=50)
    ap.add_argument("--if-samples", type=int, default=128)
    ap.add_argument("--if-quantile", type=float, default=0.99, help="anomaly threshold = this quantile of NORMAL training scores")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    print(f"Loading sessions from {args.data} ...")
    X, y, groups, info = sc.build_dataset(args.data, args.stride)
    X = X.astype(np.float32)                       # trees see float32 (same as on the device)
    sessions = sorted(set(groups))
    counts = {n: int((y == i).sum()) for i, n in enumerate(sc.CLASS_NAMES)}
    sess_per_class = {n: len({g for g, yy in zip(groups, y) if yy == i}) for i, n in enumerate(sc.CLASS_NAMES)}
    print(f"  {len(sessions)} sessions, {len(y)} windows: {counts}  sessions/class: {sess_per_class}")
    if info["synthetic"]:
        print("\n  *** SYNTHETIC DATA — pipeline smoke test only. Do NOT quote these numbers or flash this model. ***\n")
    for n in sc.CLASS_NAMES:
        if sess_per_class[n] < 2:
            raise SystemExit(f"Need at least 2 sessions of {n} for session-wise evaluation (have {sess_per_class[n]}). "
                             f"Record more sessions with tools/collect_serial.py.")
    few = [n for n in sc.CLASS_NAMES if sess_per_class[n] < 4]
    if few:
        print(f"  WARNING: fewer than 4 sessions for {few} — results will be very noisy; collect more (different days/places).")

    # ---------------- classifier: leave-one-session-out ----------------
    pred = np.zeros_like(y)
    proba_cv = np.zeros((len(y), len(sc.CLASS_NAMES)))
    for s in sessions:
        te = groups == s
        clf = make_rf(args, args.seed).fit(X[~te], y[~te])
        proba_cv[te] = clf.predict_proba(X[te])
        pred[te] = proba_cv[te].argmax(axis=1)
    cm = confusion_matrix(y, pred, labels=[0, 1, 2])
    acc = float((pred == y).mean())
    normal_n = cm[0].sum()
    false_hazard = cm[0, 2] / normal_n if normal_n else float("nan")
    false_alarm_any = (cm[0, 1] + cm[0, 2]) / normal_n if normal_n else float("nan")
    hazard_recall = cm[2, 2] / cm[2].sum() if cm[2].sum() else float("nan")
    hazard_missed_as_normal = cm[2, 0] / cm[2].sum() if cm[2].sum() else float("nan")
    print(f"  leave-one-session-out accuracy {acc:.3f} | hazard recall {hazard_recall:.3f} | NORMAL->HAZARDOUS {false_hazard:.3f}")

    # ---------------- anomaly detector: NORMAL-only ----------------
    normal_sessions = sorted({g for g, yy in zip(groups, y) if yy == 0})
    cv_normal_scores, cv_normal_thr = [], []
    if len(normal_sessions) >= 2:
        for s in normal_sessions:
            tr = (y == 0) & (groups != s)
            te = (y == 0) & (groups == s)
            m = make_if(args, args.seed).fit(X[tr])
            thr = np.quantile(iforest_score(m, X[tr]), args.if_quantile)
            sc_te = iforest_score(m, X[te])
            cv_normal_scores.append(sc_te); cv_normal_thr.append(thr)
        fp_rate_heldout = float(np.mean(np.concatenate([s > t for s, t in zip(cv_normal_scores, cv_normal_thr)])))
    else:
        fp_rate_heldout = float("nan")

    if_final = make_if(args, args.seed).fit(X[y == 0])
    train_scores = iforest_score(if_final, X[y == 0])
    threshold = float(np.quantile(train_scores, args.if_quantile))
    fire_scores = iforest_score(if_final, X[y != 0])
    detect = {sc.CLASS_NAMES[c]: float(np.mean(iforest_score(if_final, X[y == c]) > threshold)) for c in (1, 2)}
    # AUROC with held-out-normal scores (cross-validated) vs fire windows — never-seen anomalies
    if cv_normal_scores:
        auroc = float(roc_auc_score(np.r_[np.zeros(sum(map(len, cv_normal_scores))), np.ones(len(fire_scores))],
                                    np.r_[np.concatenate(cv_normal_scores), fire_scores]))
    else:
        auroc = float("nan")
    print(f"  anomaly: threshold {threshold:.4f} | held-out NORMAL false-positive rate {fp_rate_heldout:.3f} | "
          f"AUROC normal-vs-fire {auroc:.3f} | detection {detect}")

    # ---------------- final classifier on all sessions ----------------
    rf_final = make_rf(args, args.seed).fit(X, y)
    importances = sorted(zip(sc.FEATURE_NAMES, rf_final.feature_importances_), key=lambda t: -t[1])

    joblib.dump(rf_final, os.path.join(args.out, "sensor_rf.joblib"))
    joblib.dump(if_final, os.path.join(args.out, "sensor_iforest.joblib"))
    manifest = {
        "model_version": time.strftime("sensor-%Y%m%d-%H%M%S"),
        "synthetic_data": info["synthetic"],
        "data_dir": args.data,
        "class_names": sc.CLASS_NAMES,
        "feature_names": sc.FEATURE_NAMES,
        "window_size": sc.WINDOW_SIZE, "sample_interval_s": sc.SAMPLE_INTERVAL_S, "stride": args.stride,
        "rf": {"trees": args.trees, "max_depth": args.max_depth, "min_samples_leaf": args.min_leaf},
        "iforest": {"trees": args.if_trees, "max_samples": args.if_samples, "threshold": threshold,
                    "threshold_quantile": args.if_quantile},
        "dataset": {"sessions": info["sessions"], "windows_per_class": counts, "sessions_per_class": sess_per_class},
        "metrics_leave_one_session_out": {
            "accuracy": acc, "hazard_recall": hazard_recall, "hazard_missed_as_normal": hazard_missed_as_normal,
            "normal_to_hazard_rate": false_hazard, "normal_to_any_alarm_rate": false_alarm_any,
            "confusion_matrix": cm.tolist()},
        "metrics_anomaly": {"heldout_normal_false_positive_rate": fp_rate_heldout, "auroc_normal_vs_fire": auroc,
                            "detection_rate_at_threshold": detect},
        "feature_importance": [[n, float(v)] for n, v in importances],
    }
    sc.save_json(os.path.join(args.out, "sensor_model_manifest.json"), manifest)

    # ---------------- report ----------------
    banner = ("> **SYNTHETIC DATA — smoke test only. These numbers mean nothing about real fires.**\n\n"
              if info["synthetic"] else "")
    rep = f"""# Fire Sentinel — sensor model report

{banner}Model `{manifest['model_version']}` · data `{args.data}` · {len(sessions)} sessions · {len(y)} windows ({counts})

## Classifier (RandomForest, {args.trees} trees, depth <= {args.max_depth}) — leave-one-session-out
Accuracy **{acc:.3f}** · hazard recall **{hazard_recall:.3f}** (missed as NORMAL: {hazard_missed_as_normal:.3f}) ·
NORMAL->HAZARDOUS false alarm **{false_hazard:.3f}** · NORMAL->any alarm class {false_alarm_any:.3f}

Confusion matrix (rows = true, cols = predicted: {', '.join(sc.CLASS_NAMES)}):
```
{cm}
```
{per_class_report(cm)}

## Anomaly detector (IsolationForest, NORMAL-only, {args.if_trees} trees)
Threshold {threshold:.4f} (= {args.if_quantile:.0%} quantile of NORMAL training scores).
Held-out NORMAL sessions flagged anomalous: **{fp_rate_heldout:.3f}** of windows.
AUROC NORMAL vs fire windows (never seen in training): **{auroc:.3f}**.
Fraction of fire windows flagged at the threshold: {detect}

## Top features
""" + "\n".join(f"- {n}: {v:.3f}" for n, v in importances[:8]) + f"""

## Notes
- Features are baseline-relative (see sensor_common.py), so they transfer across rooms/sensor units better than raw counts.
- A session-wise split is used on purpose; windows overlap by 29/30 samples.
- Thresholds in the firmware's rule-based fusion are still hand-set; compare them with these results before trusting either.
"""
    with open(os.path.join(args.out, "sensor_report.md"), "w", encoding="utf-8") as f:
        f.write(rep)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(4.2, 3.8))
        ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(3)); ax.set_yticks(range(3))
        ax.set_xticklabels(["NORMAL", "CONTROLLED", "HAZARD"], rotation=20); ax.set_yticklabels(["NORMAL", "CONTROLLED", "HAZARD"])
        for i in range(3):
            for j in range(3):
                ax.text(j, i, int(cm[i, j]), ha="center", va="center")
        ax.set_xlabel("predicted"); ax.set_ylabel("true"); ax.set_title("Leave-one-session-out")
        fig.tight_layout(); fig.savefig(os.path.join(args.out, "sensor_confusion.png"), dpi=140); plt.close(fig)

        fig, ax = plt.subplots(figsize=(5.5, 3.4))
        ax.hist(train_scores, bins=40, alpha=.6, label="NORMAL (train)")
        ax.hist(fire_scores, bins=40, alpha=.6, label="flame / fire windows")
        ax.axvline(threshold, color="k", ls="--", label="threshold")
        ax.set_xlabel("isolation-forest anomaly score"); ax.legend(); fig.tight_layout()
        fig.savefig(os.path.join(args.out, "sensor_anomaly_scores.png"), dpi=140); plt.close(fig)
    except Exception as e:                      # plots are a nicety, never a blocker
        print(f"  (plots skipped: {e})")

    print(f"Done in {time.time()-t0:.0f}s. Artifacts in {args.out}\n  next: python ml/sensor/export_c.py --artifacts {args.out}")


if __name__ == "__main__":
    main()
