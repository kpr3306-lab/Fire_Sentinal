"""
routes/sensor_routes.py — Ignis

POST /api/sensor-data — matches the JSON shape sent by
firmware/esp32s3-cam-main/network_client.cpp's network_post_sensor_data():

{
  "device_id": "fs-AABBCCDDEEFF",
  "timestamp_ms": 123456,
  "state": "NORMAL" | "PRECURSOR" | "CONFIRMING" | "FIRE_CONFIRMED",
  "risk_score": 0-100,
  "sensors": { "temperature_c", "humidity_pct", "pressure_hpa",
               "mq2_ppm", "mq7_ppm", "mq135_ppm", "uv_index",
               "flame_detected", "reading_valid" },
  "fusion": { "temp_deviation", "gas_deviation_pct" }
}
"""

from flask import Blueprint, request, jsonify
from db import get_db
from services import risk_score_service

sensor_bp = Blueprint("sensor_routes", __name__)


@sensor_bp.route("/api/sensor-data", methods=["POST"])
def post_sensor_data():
    payload = request.get_json(force=True, silent=True)
    if not payload or "device_id" not in payload:
        return jsonify({"error": "invalid payload, device_id is required"}), 400

    conn = get_db()
    result = risk_score_service.process_sensor_reading(conn, payload)
    return jsonify({"status": "ok", **result}), 200


@sensor_bp.route("/api/sensor-data/latest", methods=["GET"])
def get_latest():
    """?device_id=... or ?room_id=... — powers the live gauge tiles."""
    device_id = request.args.get("device_id")
    room_id = request.args.get("room_id")

    conn = get_db()
    if device_id:
        row = conn.execute(
            "SELECT * FROM sensor_readings WHERE device_id = ? ORDER BY created_at DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    elif room_id:
        row = conn.execute(
            "SELECT * FROM sensor_readings WHERE room_id = ? ORDER BY created_at DESC LIMIT 1",
            (room_id,),
        ).fetchone()
    else:
        return jsonify({"error": "device_id or room_id query param required"}), 400

    if row is None:
        return jsonify({"error": "no readings yet"}), 404
    return jsonify(dict(row)), 200


@sensor_bp.route("/api/sensor-data/history", methods=["GET"])
def get_history():
    """?device_id=...&limit=50 — powers the Sensor Trends chart."""
    device_id = request.args.get("device_id")
    limit = int(request.args.get("limit", 50))
    if not device_id:
        return jsonify({"error": "device_id query param required"}), 400

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sensor_readings WHERE device_id = ? ORDER BY created_at DESC LIMIT ?",
        (device_id, limit),
    ).fetchall()
    readings = [dict(r) for r in rows]
    readings.reverse()  # chronological order for charting
    return jsonify(readings), 200
