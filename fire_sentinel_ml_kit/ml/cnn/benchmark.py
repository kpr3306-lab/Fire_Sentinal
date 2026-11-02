"""
ml/cnn/benchmark.py — FP32 Keras vs FP32 TFLite vs INT8 TFLite: accuracy, hazardous recall,
size, host latency. (Host latency is NOT ESP32 latency — measure that on-device with
micros() around Invoke() and put the real number in the report.)

    python ml/cnn/benchmark.py --data ml/cnn/dataset/split --img 96
"""
import argparse, os, time
import numpy as np
from cnn_common import (load_split, predict_any, metrics_from_probs, save_json,
                        _tflite_io, run_tflite_once)


def latency(path, ds, n=100):
    it, inp, out = _tflite_io(path)
    xs = [x.numpy() for x, _ in ds.unbatch().take(10)]
    for _ in range(5): run_tflite_once(it, inp, out, xs[0])
    t = []
    for k in range(n):
        s = time.perf_counter(); run_tflite_once(it, inp, out, xs[k % len(xs)]); t.append((time.perf_counter() - s) * 1e3)
    return float(np.mean(t)), float(np.percentile(t, 95))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--img", type=int, default=96)
    ap.add_argument("--art", default="ml/cnn/artifacts")
    ap.add_argument("--interp", default="area")
    a = ap.parse_args()
    ds, _ = load_split(a.data, "test", a.img, 32, False, a.interp)
    cands = {"keras_fp32": "fire_cnn.keras", "tflite_fp32": "fire_cnn_fp32.tflite", "tflite_int8": "fire_cnn_int8.tflite"}
    res = {}
    for k, fn in cands.items():
        p = os.path.join(a.art, fn)
        probs, labels = predict_any(p, ds); m = metrics_from_probs(probs, labels)
        r = {"size_kb": round(os.path.getsize(p) / 1024, 1), "accuracy": m["accuracy"],
             "macro_f1": m["macro_f1"], "hazardous_recall": m["hazardous_recall"],
             "false_hazard_alarm_rate": m["false_hazard_alarm_rate"]}
        if fn.endswith(".tflite"): r["host_latency_ms_mean"], r["host_latency_ms_p95"] = latency(p, ds)
        res[k] = r
    f, q = res["tflite_fp32"], res["tflite_int8"]
    res["delta_int8_vs_fp32"] = {"accuracy": q["accuracy"] - f["accuracy"],
                                 "hazardous_recall": q["hazardous_recall"] - f["hazardous_recall"],
                                 "size_reduction_x": round(f["size_kb"] / q["size_kb"], 2)}
    save_json(res, os.path.join(a.art, "benchmark.json"))
    print(f"{'model':14}{'size KB':>9}{'acc':>8}{'haz recall':>12}{'FA rate':>9}{'ms(host)':>10}")
    for k in cands:
        r = res[k]; print(f"{k:14}{r['size_kb']:>9}{r['accuracy']:>8.4f}{r['hazardous_recall']:>12.4f}"
                          f"{r['false_hazard_alarm_rate']:>9.4f}{r.get('host_latency_ms_mean', float('nan')):>10.2f}")
    print("INT8 vs FP32:", res["delta_int8_vs_fp32"])


if __name__ == "__main__":
    main()
