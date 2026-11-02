"""
routes/profile_routes.py — Fire Sentinel Prototype 2

Rooms, per-room appliances (electrical/gas equipment declared by the user),
and emergency contacts. Appliance data feeds a minor contextual note in
incident reports — never an automatic diagnosis.
"""

from flask import Blueprint, request, jsonify
from db import get_db

profile_bp = Blueprint("profile_routes", __name__)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
@profile_bp.route("/api/rooms", methods=["GET"])
def list_rooms():
    conn = get_db()
    rows = conn.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows]), 200


@profile_bp.route("/api/rooms", methods=["POST"])
def create_room():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "name is required"}), 400

    conn = get_db()
    cursor = conn.execute("INSERT INTO rooms (name) VALUES (?)", (name,))
    conn.commit()
    return jsonify({"id": cursor.lastrowid, "name": name}), 201


@profile_bp.route("/api/rooms/<int:room_id>", methods=["DELETE"])
def delete_room(room_id):
    conn = get_db()
    conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
    conn.commit()
    return jsonify({"status": "deleted"}), 200


# ---------------------------------------------------------------------------
# Appliances (per room)
# ---------------------------------------------------------------------------
@profile_bp.route("/api/rooms/<int:room_id>/appliances", methods=["GET"])
def list_appliances(room_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM appliances WHERE room_id = ? ORDER BY category, name", (room_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@profile_bp.route("/api/rooms/<int:room_id>/appliances", methods=["POST"])
def add_appliance(room_id):
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    category = data.get("category")  # "electrical" or "gas"
    notes = data.get("notes", "")

    if not name or category not in ("electrical", "gas"):
        return jsonify({"error": "name is required and category must be 'electrical' or 'gas'"}), 400

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO appliances (room_id, name, category, notes) VALUES (?, ?, ?, ?)",
        (room_id, name, category, notes),
    )
    conn.commit()
    return jsonify({"id": cursor.lastrowid, "name": name, "category": category}), 201


@profile_bp.route("/api/appliances/<int:appliance_id>", methods=["DELETE"])
def delete_appliance(appliance_id):
    conn = get_db()
    conn.execute("DELETE FROM appliances WHERE id = ?", (appliance_id,))
    conn.commit()
    return jsonify({"status": "deleted"}), 200


# ---------------------------------------------------------------------------
# Emergency contacts
# ---------------------------------------------------------------------------
@profile_bp.route("/api/contacts", methods=["GET"])
def list_contacts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM emergency_contacts ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows]), 200


@profile_bp.route("/api/contacts", methods=["POST"])
def add_contact():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    phone = data.get("phone")
    relation = data.get("relation", "")

    if not name or not phone:
        return jsonify({"error": "name and phone are required"}), 400

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO emergency_contacts (name, phone, relation) VALUES (?, ?, ?)",
        (name, phone, relation),
    )
    conn.commit()
    return jsonify({"id": cursor.lastrowid, "name": name, "phone": phone}), 201


@profile_bp.route("/api/contacts/<int:contact_id>", methods=["DELETE"])
def delete_contact(contact_id):
    conn = get_db()
    conn.execute("DELETE FROM emergency_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    return jsonify({"status": "deleted"}), 200
