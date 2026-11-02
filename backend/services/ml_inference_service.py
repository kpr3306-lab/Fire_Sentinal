"""
services/ml_inference_service.py — Fire Sentinel Prototype 2 (REAL implementation; replaces the stub).

Drop-in: same classify_snapshot() signature and ClassificationResult as the stub, so nothing in routes/
changes. Looks for the model at fire_sentinel_ml_kit/ml/cnn/artifacts/fire_cnn_int8.tflite (override: FIRE_MODEL_PATH).

Edge cases handled: model file missing -> PENDING_MODEL (never crashes the upload path);
unreadable/corrupt image -> PENDING_MODEL; concurrent Flask threads -> interpreter guarded by a lock;
model hot-swapped on disk -> reloaded (mtime check).
"""
import os
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image

try:                                   # lightweight runtime if installed, else full TF
    from ai_edge_litert.interpreter import Interpreter
except Exception:
    try:
        from tflite_runtime.interpreter import Interpreter
    except Exception:
        try:
            from tensorflow.lite.python.interpreter import Interpreter
        except Exception:
            Interpreter = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.getenv("FIRE_MODEL_PATH",
                       os.path.join(BASE, "..", "fire_sentinel_ml_kit", "ml", "cnn", "artifacts", "fire_cnn_int8.tflite"))
LABELS = ["NO_FLAME", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"]    # same order as training CLASS_NAMES

_lock = threading.Lock()
_state = {"mtime": None, "it": None, "inp": None, "out": None}


@dataclass
class ClassificationResult:
    label: str          # NO_FLAME | CONTROLLED_FLAME | HAZARDOUS_FIRE | PENDING_MODEL
    confidence: float   # 0.0-1.0


def _load():
    if Interpreter is None or not os.path.exists(MODEL_PATH):
        _state.update(mtime=None, it=None); return False
    m = os.path.getmtime(MODEL_PATH)
    if _state["it"] is not None and _state["mtime"] == m:
        return True
    it = Interpreter(model_path=MODEL_PATH, num_threads=1)
    it.allocate_tensors()
    _state.update(mtime=m, it=it, inp=it.get_input_details()[0], out=it.get_output_details()[0])
    return True


def classify_snapshot(image_path: str) -> ClassificationResult:
    pending = ClassificationResult(label="PENDING_MODEL", confidence=0.0)
    try:
        with _lock:
            if not _load():
                return pending
            inp, out, it = _state["inp"], _state["out"], _state["it"]
            h, w = int(inp["shape"][1]), int(inp["shape"][2])
            with Image.open(image_path) as im:
                # BOX ~ 'area' resampling, matching the training pipeline's interpolation.
                x = np.asarray(im.convert("RGB").resize((w, h), Image.BOX), dtype=np.float32)[None]
            if inp["dtype"] == np.int8:
                s, zp = inp["quantization"]
                x = np.clip(np.round(x / s + zp), -128, 127).astype(np.int8)
            it.set_tensor(inp["index"], x)
            it.invoke()
            o = it.get_tensor(out["index"])[0]
            if out["dtype"] == np.int8:
                s, zp = out["quantization"]; o = (o.astype(np.float32) - zp) * s
            k = int(np.argmax(o))
            return ClassificationResult(label=LABELS[k], confidence=float(o[k]))
    except Exception as e:             # corrupt image, runtime error, etc. — never break the upload path
        print(f"[ml_inference] failed for {image_path}: {e}")
        return pending
