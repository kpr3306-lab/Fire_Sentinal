"""
ml/cnn/cnn_common.py — shared helpers for the Fire Sentinel 3-class CNN pipeline.

Class order is FIXED and is also written into model_manifest.json. The ESP32
firmware and backend index the model output by this order, so never reorder.
"""
import json
import os
import numpy as np
import tensorflow as tf

CLASS_NAMES = ["no_fire", "controlled_flame", "hazardous_fire"]      # folder names
DISPLAY = {"no_fire": "NO_FLAME", "controlled_flame": "CONTROLLED_FLAME",
           "hazardous_fire": "HAZARDOUS_FIRE"}                        # names used by backend/DB/firmware
HAZ = CLASS_NAMES.index("hazardous_fire")
SEED = 42


def load_split(data_dir, split, img, batch=32, shuffle=False, interpolation="area"):
    """Returns (dataset, file_paths). Pixels are float32 in [0,255] — the model
    rescales internally, so the exact same raw 0-255 values can be fed on device."""
    ds = tf.keras.utils.image_dataset_from_directory(
        os.path.join(data_dir, split), labels="inferred", label_mode="int",
        class_names=CLASS_NAMES, image_size=(img, img), batch_size=batch,
        shuffle=shuffle, seed=SEED, interpolation=interpolation)
    return ds, list(ds.file_paths)


def predict_keras(model, ds):
    probs, labels = [], []
    for x, y in ds:
        probs.append(model.predict(x, verbose=0))
        labels.append(y.numpy())
    return np.concatenate(probs), np.concatenate(labels)


def _tflite_io(path):
    it = tf.lite.Interpreter(model_path=path, num_threads=1)
    it.allocate_tensors()
    return it, it.get_input_details()[0], it.get_output_details()[0]


def run_tflite_once(it, inp, out, x):
    """x: float32 (H,W,3) in [0,255]. Handles float and int8 models."""
    xi = x[None].astype(np.float32)
    if inp["dtype"] == np.int8:
        s, zp = inp["quantization"]
        xi = np.clip(np.round(xi / s + zp), -128, 127).astype(np.int8)
    it.set_tensor(inp["index"], xi)
    it.invoke()
    o = it.get_tensor(out["index"])[0]
    if out["dtype"] == np.int8:
        s, zp = out["quantization"]
        o = (o.astype(np.float32) - zp) * s
    return o


def predict_tflite(path, ds):
    it, inp, out = _tflite_io(path)
    probs, labels = [], []
    for x, y in ds.unbatch():
        probs.append(run_tflite_once(it, inp, out, x.numpy()))
        labels.append(int(y.numpy()))
    return np.array(probs), np.array(labels)


def predict_any(model_path, ds):
    if model_path.endswith(".tflite"):
        return predict_tflite(model_path, ds)
    return predict_keras(tf.keras.models.load_model(model_path), ds)


def metrics_from_probs(probs, labels):
    from sklearn.metrics import (accuracy_score, confusion_matrix,
                                 precision_recall_fscore_support)
    pred = probs.argmax(1)
    p, r, f, s = precision_recall_fscore_support(labels, pred, labels=range(3), zero_division=0)
    cm = confusion_matrix(labels, pred, labels=range(3))
    haz = labels == HAZ
    return {
        "accuracy": float(accuracy_score(labels, pred)),
        "per_class": {CLASS_NAMES[i]: {"precision": float(p[i]), "recall": float(r[i]),
                                       "f1": float(f[i]), "support": int(s[i])} for i in range(3)},
        "macro_f1": float(np.mean(f)),
        "hazardous_recall": float(r[HAZ]),
        # the dangerous failure: real hazardous fire called anything else
        "hazardous_miss_rate": float((pred[haz] != HAZ).mean()) if haz.any() else None,
        # real hazardous fire called NO flame at all (worst case)
        "hazardous_to_no_fire_rate": float((pred[haz] == 0).mean()) if haz.any() else None,
        # harmless scene raising a hazardous alarm
        "false_hazard_alarm_rate": float((pred[~haz] == HAZ).mean()) if (~haz).any() else None,
        "confusion_matrix": cm.tolist(),
    }


def save_json(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
