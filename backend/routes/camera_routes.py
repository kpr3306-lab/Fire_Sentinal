"""
routes/camera_routes.py — Fire Sentinel Prototype 2

Three jobs:
  1. POST /api/camera/snapshot        — receives the multipart upload from
     firmware's network_post_snapshot() whenever the camera fires (any
     reason — precursor/confirming/fire_confirmed/on_demand). ALWAYS saved,
     per the "snapshot should always be visible when user wants to see" rule.
  2. GET  /api/camera/capture-proxy   — dashboard "Turn On" button hits this;
     backend fetches the device's own /capture endpoint live and streams it
     back. Keeps the dashboard from needing direct network access to the
     device's LAN address itself, and lets us honor ip_override transparently.
  3. GET  /api/camera/snapshots       — gallery listing + file serving.
"""

import faulthandler
import os
import time
import requests
from flask import Blueprint, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename
from db import get_db
import json
from services import ml_inference_service, yolo_service, hazard_service
import config

camera_bp = Blueprint("camera_routes", __name__)


def _resolve_device_address(conn, device_id):
    row = conn.execute(
        "SELECT ip, port, ip_override, port_override, use_override FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return None, None
    if row["use_override"]:
        return row["ip_override"], row["port_override"]
    return row["ip"], row["port"]


@camera_bp.route("/api/camera/snapshot", methods=["POST"])
def upload_snapshot():
    device_id = request.form.get("device_id")
    reason = request.form.get("reason", "unknown")
    image_file = request.files.get("image")

    if not device_id or image_file is None:
        return jsonify({"error": "device_id and image are required"}), 400

    conn = get_db()
    room_row = conn.execute("SELECT room_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    room_id = room_row["room_id"] if room_row else None

    device_dir = os.path.join(config.SNAPSHOT_STORAGE_DIR, secure_filename(device_id))
    os.makedirs(device_dir, exist_ok=True)

    filename = f"{int(time.time() * 1000)}_{secure_filename(reason)}.jpg"
    file_path = os.path.join(device_dir, filename)
    image_file.save(file_path)

    # Firmware v2.3 runs the same CNN + YOLO on the device and sends the results; use them when the
    # backend's own models are not installed, or have not finished.
    device_cnn = request.form.get("cnn_class")
    device_cls = None
    if device_cnn in ("NO_FLAME", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"):
        try:
            conf = min(1.0, max(0.0, float(request.form.get("cnn_conf", 0))))
        except ValueError:
            conf = 0.0
        device_cls = ml_inference_service.ClassificationResult(label=device_cnn, confidence=conf)

    # Record the snapshot before the models run, so a slow or stuck model can never lose it from the gallery.
    # It starts with the device's own result, so the dashboard has one even if the backend models hang.
    cursor = conn.execute(
        """INSERT INTO snapshots (device_id, room_id, reason, file_path, classification, confidence, detector_status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (device_id, room_id, reason, file_path,
         device_cls.label if device_cls else "PENDING_MODEL", device_cls.confidence if device_cls else 0.0),
    )
    snapshot_id = cursor.lastrowid
    conn.execute(
        """INSERT INTO events (device_id, room_id, event_type, to_state, message, snapshot_id)
           VALUES (?, ?, 'SNAPSHOT_CAPTURED', ?, ?, ?)""",
        (device_id, room_id, reason, f"Snapshot captured ({reason})", snapshot_id),
    )
    conn.commit()

    # If a model ever hangs, print every thread's stack after 15 s so the console shows where.
    faulthandler.dump_traceback_later(15)
    try:
        # CNN classifier (PENDING_MODEL until its model file is in place).
        classification = ml_inference_service.classify_snapshot(file_path)

        # YOLO flame detector + hazard logic. Both are optional and never raise: if the detector is off the
        # snapshot is still saved, with detector_status = 'unavailable'.
        detection = yolo_service.detect_flames(file_path)
    finally:
        faulthandler.cancel_dump_traceback_later()

    if classification.label == "PENDING_MODEL" and device_cls:
        classification = device_cls
    if detection.status == "unavailable" and "yolo_boxes" in request.form:
        detection = yolo_service.from_device_boxes(request.form["yolo_boxes"])
    previous_area = hazard_service.previous_flame_area(conn, device_id) if detection.status == "ok" else None
    hazard = hazard_service.assess(classification.label, detection, previous_area)
    detector_ran = detection.status == "ok"

    conn.execute(
        """UPDATE snapshots SET classification = ?, confidence = ?, detector_status = ?, flame_count = ?,
                                flame_area_ratio = ?, flame_boxes = ?, flame_growth = ?, hazard_level = ?,
                                hazard_reasons = ?
           WHERE id = ?""",
        (classification.label, classification.confidence,
         detection.status,
         detection.n_flames if detector_ran else None,
         detection.area_ratio if detector_ran else None,
         json.dumps(detection.boxes) if detector_ran else None,
         hazard.growth, hazard.level, json.dumps(hazard.reasons), snapshot_id),
    )
    conn.commit()

    return jsonify({"status": "saved", "snapshot_id": snapshot_id, "classification": classification.label,
                    "hazard_level": hazard.level, "detector_status": detection.status,
                    "flame_count": detection.n_flames if detector_ran else None}), 200


@camera_bp.route("/api/camera/capture-proxy", methods=["GET"])
def capture_proxy():
    """Dashboard's 'Turn On' button calls this. Backend fetches the device's
    own on-demand /capture endpoint and streams the JPEG straight through —
    the dashboard never needs to know or care about the device's raw LAN IP.
    """
    device_id = request.args.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id query param required"}), 400

    conn = get_db()
    ip, port = _resolve_device_address(conn, device_id)
    if not ip:
        return jsonify({"error": "device has no known address yet (not registered or never seen)"}), 503

    try:
        # (connect, read): the board can stall several seconds before the first byte on a weak hotspot link
        resp = requests.get(f"http://{ip}:{port}/capture", timeout=(5, 30))
        if resp.status_code != 200:
            return jsonify({"error": f"device returned status {resp.status_code}"}), 502
        return Response(resp.content, mimetype="image/jpeg")
    except requests.RequestException as e:
        return jsonify({"error": f"could not reach device at {ip}:{port}: {e}"}), 502


@camera_bp.route("/api/camera/snapshots", methods=["GET"])
def list_snapshots():
    """?device_id=...&room_id=...&limit=50 — powers the snapshot gallery / history."""
    device_id = request.args.get("device_id")
    room_id = request.args.get("room_id")
    limit = int(request.args.get("limit", 50))

    conn = get_db()
    if device_id:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE device_id = ? ORDER BY created_at DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    elif room_id:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE room_id = ? ORDER BY created_at DESC LIMIT ?",
            (room_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM snapshots ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    return jsonify([dict(r) for r in rows]), 200


@camera_bp.route("/api/camera/snapshots/<int:snapshot_id>/file", methods=["GET"])
def get_snapshot_file(snapshot_id):
    conn = get_db()
    row = conn.execute("SELECT file_path FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if row is None or not os.path.exists(row["file_path"]):
        return jsonify({"error": "snapshot not found"}), 404
    return send_file(row["file_path"], mimetype="image/jpeg")
