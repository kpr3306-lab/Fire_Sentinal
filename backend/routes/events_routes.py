"""
routes/events_routes.py — Fire Sentinel
Powers the Detection Timeline and Recent Events dashboard widgets.
"""

from flask import Blueprint, request, jsonify
from db import get_db

events_bp = Blueprint("events_routes", __name__)


@events_bp.route("/api/events", methods=["GET"])
def list_events():
    """?room_id=...&device_id=...&limit=50"""
    room_id = request.args.get("room_id")
    device_id = request.args.get("device_id")
    limit = int(request.args.get("limit", 50))

    conn = get_db()
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    if room_id:
        query += " AND room_id = ?"
        params.append(room_id)
    if device_id:
        query += " AND device_id = ?"
        params.append(device_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@events_bp.route("/api/events/recent", methods=["GET"])
def recent_events():
    """Small unfiltered feed for the 'Recent Events' sidebar widget."""
    limit = int(request.args.get("limit", 10))
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200
