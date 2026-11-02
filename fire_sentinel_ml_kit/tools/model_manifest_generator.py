"""
tools/model_manifest_generator.py — writes model_manifest.json (read by GET /api/model-info and by the
device's hot-swap check). Writes to ml/cnn/model_manifest.json AND next to the model for the SD card.

    python tools/model_manifest_generator.py --version 1.0.0
"""
import argparse, hashlib, json, os, datetime


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", default="ml/cnn/artifacts")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default="ml/cnn/model_manifest.json")
    a = ap.parse_args()
    ld = lambda n: json.load(open(os.path.join(a.art, n)))
    q, t = ld("quant_info.json"), ld("train_info.json")
    ev = ld("eval_int8/metrics.json")           # evaluate.py --tag int8 on the INT8 .tflite
    mp = os.path.join(a.art, "fire_cnn_int8.tflite")
    man = {
        "status": "trained", "version": a.version, "file": "fire_cnn_int8.tflite",
        "sha256": sha256(mp), "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "backbone": f"MobileNetV2 alpha={t['alpha']}", "pretrained": t["pretrained"],
        "input": {"shape": q["input_shape"], "dtype": "int8", "scale": q["input_scale"],
                  "zero_point": q["input_zero_point"], "resize": t["interp"],
                  "note": "feed raw RGB 0-255 pixels quantised with scale/zero_point; rescaling is inside the model"},
        "output": {"classes": t["class_names"], "labels": ["NO_FLAME", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"],
                   "scale": q["output_scale"], "zero_point": q["output_zero_point"]},
        "size_bytes": q["int8_bytes"], "fp32_size_bytes": q["fp32_bytes"],
        "train_counts": t["train_counts"],
        "test": {"n": ev["n_test"], "accuracy": ev["accuracy"], "macro_f1": ev["macro_f1"],
                 "hazardous_recall": ev["hazardous_recall"],
                 "false_hazard_alarm_rate": ev["false_hazard_alarm_rate"],
                 "confusion_matrix": ev["confusion_matrix"]},
    }
    json.dump(man, open(a.out, "w"), indent=2)
    json.dump(man, open(os.path.join(a.art, "model_manifest.json"), "w"), indent=2)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
