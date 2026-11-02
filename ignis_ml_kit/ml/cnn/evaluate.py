"""
ml/cnn/evaluate.py — test-set evaluation for the viva: accuracy, per-class P/R/F1,
confusion matrix (PNG), hazardous false-negative list, hazardous-threshold sweep.
Works on .keras, FP32 .tflite and INT8 .tflite.

    python ml/cnn/evaluate.py --model ml/cnn/artifacts/fire_cnn.keras --data ml/cnn/dataset/split --img 96 --tag fp32
"""
import argparse, csv, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cnn_common import (CLASS_NAMES, HAZ, DISPLAY, load_split, predict_any,
                        metrics_from_probs, save_json)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--img", type=int, default=96)
    ap.add_argument("--split", default="test")
    ap.add_argument("--tag", default="model")
    ap.add_argument("--out", default="ml/cnn/artifacts")
    ap.add_argument("--interp", default="area")
    a = ap.parse_args()

    ds, paths = load_split(a.data, a.split, a.img, 32, False, a.interp)
    probs, labels = predict_any(a.model, ds)
    m = metrics_from_probs(probs, labels)
    od = os.path.join(a.out, f"eval_{a.tag}"); os.makedirs(od, exist_ok=True)

    # threshold sweep on P(hazardous): recall vs false-alarm trade-off
    sweep = []
    haz = labels == HAZ
    for t in np.round(np.arange(0.05, 0.96, 0.05), 2):
        pr = probs[:, HAZ] >= t
        sweep.append({"threshold": float(t),
                      "hazardous_recall": float(pr[haz].mean()) if haz.any() else None,
                      "false_hazard_alarm_rate": float(pr[~haz].mean()) if (~haz).any() else None})
    m["hazard_threshold_sweep"] = sweep
    m["n_test"] = int(len(labels)); m["model"] = a.model
    save_json(m, os.path.join(od, "metrics.json"))

    # confusion matrix PNG (raw + row-normalised)
    cm = np.array(m["confusion_matrix"]); cmn = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(5.6, 4.8)); ax.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{cm[i, j]}\n({cmn[i, j]:.0%})", ha="center", va="center",
                    color="white" if cmn[i, j] > .5 else "black")
    ax.set_xticks(range(3), [DISPLAY[c] for c in CLASS_NAMES], rotation=20, ha="right", fontsize=8)
    ax.set_yticks(range(3), [DISPLAY[c] for c in CLASS_NAMES], fontsize=8)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True"); ax.set_title(f"Confusion matrix — {a.tag}")
    fig.tight_layout(); fig.savefig(os.path.join(od, "confusion_matrix.png"), dpi=160); plt.close(fig)

    # every misclassified image, hazardous misses first (false-negative analysis)
    pred = probs.argmax(1)
    with open(os.path.join(od, "misclassified.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["file", "true", "pred", "p_no_fire", "p_controlled", "p_hazardous"])
        bad = [i for i in range(len(labels)) if pred[i] != labels[i]]
        bad.sort(key=lambda i: (labels[i] != HAZ, -probs[i].max()))
        for i in bad:
            w.writerow([paths[i], CLASS_NAMES[labels[i]], CLASS_NAMES[pred[i]], *[f"{p:.3f}" for p in probs[i]]])

    print(f"acc={m['accuracy']:.4f}  macroF1={m['macro_f1']:.4f}  "
          f"hazardous_recall={m['hazardous_recall']:.4f}  false_hazard_alarm={m['false_hazard_alarm_rate']:.4f}")
    print("confusion matrix (rows=true):"); print(cm)
    print("outputs ->", od)


if __name__ == "__main__":
    main()
