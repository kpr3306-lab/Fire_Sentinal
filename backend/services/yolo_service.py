"""
services/yolo_service.py — Fire Sentinel Prototype 2

Runs the YOLO11n flame detector (ml/yolo -> fire_yolo.pt) on one snapshot.

Design rules
  * OPTIONAL. If the weights file is missing, or `ultralytics` isn't installed, detect_flames() returns
    status "unavailable" and the upload path carries on. It never raises.
  * "ok" with 0 flames means "the detector looked and found nothing" — which, at ~57% box recall, is NOT
    proof of no fire. Callers must treat it as unknown, and hazard_service does.
  * One model instance, guarded by a lock (Flask can serve requests on several threads); reloaded if the
    weights file changes on disk.
"""
import json
import os
import threading
from dataclasses import dataclass, field

import config

_lock = threading.Lock()
_state = {"mtime": None, "model": None}


@dataclass
class DetectionResult:
    status: str                      # ok | unavailable | error
    n_flames: int = 0
    area_ratio: float = 0.0          # union of all flame boxes as a share of the frame, 0-1
    boxes: list = field(default_factory=list)   # [x1, y1, x2, y2, conf], coordinates normalised 0-1


def _load():
    path = config.YOLO_MODEL_PATH
    if not os.path.exists(path):
        _state.update(mtime=None, model=None)
        return None
    mtime = os.path.getmtime(path)
    if _state["model"] is not None and _state["mtime"] == mtime:
        return _state["model"]
    from ultralytics import YOLO          # imported lazily so the backend starts without ultralytics
    _state.update(model=YOLO(path), mtime=mtime)
    return _state["model"]


def _warm():
    try:
        with _lock:
            _load()
    except Exception as e:                          # ultralytics missing or bad weights: uploads report 'unavailable'
        print(f"[yolo_service] warm-up skipped: {e}")


def warm_up_async():
    """Load the detector at server start. The first load (PyTorch import) takes longer than the board's
    6 s snapshot-upload timeout, so loading it lazily would drop the first snapshot after every restart."""
    if not config.DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":   # skip the reloader's parent process
        threading.Thread(target=_warm, daemon=True).start()


def union_area(boxes, grid=128):
    """Share of the frame covered by the union of the boxes (overlapping boxes aren't double counted)."""
    if not boxes:
        return 0.0
    import numpy as np
    mask = np.zeros((grid, grid), dtype=bool)
    for x1, y1, x2, y2, *_ in boxes:
        x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        mask[int(y1 * grid):int(np.ceil(y2 * grid)), int(x1 * grid):int(np.ceil(x2 * grid))] = True
    return float(mask.mean())


def from_device_boxes(raw: str) -> DetectionResult:
    """Boxes computed on the ESP32 (firmware vision.cpp), same [x1, y1, x2, y2, conf] format. Untrusted input."""
    try:
        boxes = [[min(1.0, max(0.0, float(v))) for v in b[:5]] for b in json.loads(raw) if len(b) >= 5]
    except (ValueError, TypeError):
        return DetectionResult(status="error")
    return DetectionResult(status="ok", n_flames=len(boxes), area_ratio=union_area(boxes), boxes=boxes)


def detect_flames(image_path: str) -> DetectionResult:
    # A stuck warm-up holds the lock forever; skip the detector instead of hanging the upload past the board's timeout.
    if not _lock.acquire(timeout=3):
        print("[yolo_service] detector busy or still loading — skipped for this snapshot")
        return DetectionResult(status="unavailable")
    try:
        try:
            model = _load()
            if model is None:
                return DetectionResult(status="unavailable")
            res = model.predict(image_path, conf=config.YOLO_CONF_THRESHOLD,
                                imgsz=config.YOLO_IMGSZ, verbose=False)[0]
            if res.boxes is None or len(res.boxes) == 0:
                return DetectionResult(status="ok")
            coords = res.boxes.xyxyn.tolist()      # normalised x1,y1,x2,y2
            confs = res.boxes.conf.tolist()
        finally:
            _lock.release()
        boxes = [[round(v, 4) for v in c] + [round(float(p), 3)] for c, p in zip(coords, confs)]
        return DetectionResult(status="ok", n_flames=len(boxes), area_ratio=union_area(boxes), boxes=boxes)
    except ImportError:
        print("[yolo_service] ultralytics is not installed — detector disabled")
        return DetectionResult(status="unavailable")
    except Exception as e:                          # corrupt image, runtime error ... never break uploads
        print(f"[yolo_service] detection failed for {image_path}: {e}")
        return DetectionResult(status="error")
