"""
routes/device_routes.py — Fire Sentinel

This is what eliminates the "reflash to change room/IP" problem:
  - POST /api/device/register  — device self-announces on boot + every 60s
  - GET  /api/devices          — dashboard's device list / System page
  - PUT  /api/devices/<id>/room     — assign a device to a room (dashboard-side, not firmware)
  - PUT  /api/devices/<id>/override — pin a manual IP/port, or clear the override
"""

from flask import Blueprint, request, jsonify
from db import get_db

device_bp = Blueprint("device_routes", __name__)


@device_bp.route("/api/device/register", methods=["POST"])
def register_device():
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    conn = get_db()
    conn.execute(
        """INSERT INTO devices (device_id, device_name, ip, port, rssi, last_seen_at)
           VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(device_id) DO UPDATE SET
             device_name = excluded.device_name,
             ip = excluded.ip,
             port = excluded.port,
             rssi = excluded.rssi,
             last_seen_at = CURRENT_TIMESTAMP""",
        (device_id, data.get("device_name"), data.get("ip"), data.get("port"), data.get("rssi")),
    )
    conn.commit()
    return jsonify({"status": "registered", "device_id": device_id}), 200


@device_bp.route("/api/devices", methods=["GET"])
def list_devices():
    conn = get_db()
    rows = conn.execute(
        """SELECT d.*, r.name AS room_name FROM devices d
           LEFT JOIN rooms r ON d.room_id = r.id
           ORDER BY d.last_seen_at DESC"""
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@device_bp.route("/api/devices/<device_id>", methods=["GET"])
def get_device(device_id):
    conn = get_db()
    row = conn.execute(
        """SELECT d.*, r.name AS room_name FROM devices d
           LEFT JOIN rooms r ON d.room_id = r.id
           WHERE d.device_id = ?""",
        (device_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "device not found"}), 404
    return jsonify(dict(row)), 200


@device_bp.route("/api/devices/<device_id>/room", methods=["PUT"])
def assign_room(device_id):
    data = request.get_json(force=True, silent=True) or {}
    room_id = data.get("room_id")  # null/None is valid — unassigns the device

    conn = get_db()
    existing = conn.execute("SELECT device_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if existing is None:
        return jsonify({"error": "device not found"}), 404

    conn.execute("UPDATE devices SET room_id = ? WHERE device_id = ?", (room_id, device_id))
    conn.commit()
    return jsonify({"status": "updated", "device_id": device_id, "room_id": room_id}), 200


@device_bp.route("/api/devices/<device_id>/override", methods=["PUT"])
def set_override(device_id):
    """Lets the dashboard pin a manual IP/port for this device, bypassing
    self-registration — or clear the override to go back to auto-discovery.
    Body: {"ip": "192.168.1.50", "port": 80, "use_override": true}
       or {"use_override": false} to clear it.
    """
    data = request.get_json(force=True, silent=True) or {}
    use_override = bool(data.get("use_override", True))

    conn = get_db()
    existing = conn.execute("SELECT device_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if existing is None:
        return jsonify({"error": "device not found"}), 404

    conn.execute(
        """UPDATE devices SET ip_override = ?, port_override = ?, use_override = ?
           WHERE device_id = ?""",
        (data.get("ip"), data.get("port"), int(use_override), device_id),
    )
    conn.commit()
    return jsonify({"status": "updated", "device_id": device_id, "use_override": use_override}), 200
