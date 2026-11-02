"""
ml/cnn/quantize_int8.py — FP32 + full-integer INT8 TFLite export.

Representative data = real TRAIN images (raw 0-255), never val/test. Input and
output tensors are int8; the model's input scale/zero-point are printed and
saved so the firmware knows how to convert camera pixels (typically
int8_in = pixel - 128 when scale=1, zero_point=-128).

    python ml/cnn/quantize_int8.py --model ml/cnn/artifacts/fire_cnn.keras --data ml/cnn/dataset/split --img 96
"""
import argparse, os
import numpy as np
import tensorflow as tf
from cnn_common import load_split, save_json, _tflite_io


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--img", type=int, default=96)
    ap.add_argument("--n-rep", type=int, default=300)
    ap.add_argument("--out", default="ml/cnn/artifacts")
    ap.add_argument("--interp", default="area")
    a = ap.parse_args()

    model = tf.keras.models.load_model(a.model)
    ds, _ = load_split(a.data, "train", a.img, 1, True, a.interp)
    reps = [x.numpy().astype(np.float32) for x, _ in ds.take(a.n_rep)]
    if len(reps) < 50: print(f"[warn] only {len(reps)} representative images; use >=200 for stable INT8")

    def rep():
        for r in reps: yield [r]

    fp = tf.lite.TFLiteConverter.from_keras_model(model).convert()
    open(os.path.join(a.out, "fire_cnn_fp32.tflite"), "wb").write(fp)

    c = tf.lite.TFLiteConverter.from_keras_model(model)
    c.optimizations = [tf.lite.Optimize.DEFAULT]
    c.representative_dataset = rep
    c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    c.inference_input_type = tf.int8
    c.inference_output_type = tf.int8
    q = c.convert()
    p = os.path.join(a.out, "fire_cnn_int8.tflite"); open(p, "wb").write(q)

    _, i, o = _tflite_io(p)
    info = {"input_shape": [int(v) for v in i["shape"]], "input_dtype": "int8",
            "input_scale": float(i["quantization"][0]), "input_zero_point": int(i["quantization"][1]),
            "output_scale": float(o["quantization"][0]), "output_zero_point": int(o["quantization"][1]),
            "fp32_bytes": len(fp), "int8_bytes": len(q), "n_representative": len(reps)}
    save_json(info, os.path.join(a.out, "quant_info.json"))
    print(info)


if __name__ == "__main__":
    main()
