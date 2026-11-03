"""
routes/alerts_routes.py — Fire Sentinel

Alert SENDING itself is triggered internally by services/risk_score_service.py
on state changes — this blueprint just exposes history and a manual test-send
endpoint, useful for confirming your Telegram bot token / Gmail app password
are wired correctly before relying on them during a live demo.
"""

from flask import Blueprint, request, jsonify
from db import get_db
from services import telegram_service, email_service

alerts_bp = Blueprint("alerts_routes", __name__)


@alerts_bp.route("/api/alerts/history", methods=["GET"])
def alert_history():
    limit = int(request.args.get("limit", 50))
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY sent_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@alerts_bp.route("/api/alerts/test", methods=["POST"])
def test_alert():
    """Body: {"channel": "telegram" | "email"} — sends a harmless test message
    so you can confirm credentials work before your professor is watching.
    """
    data = request.get_json(force=True, silent=True) or {}
    channel = data.get("channel")

    if channel == "telegram":
        success, error = telegram_service.send_text("Fire Sentinel test alert — Telegram is wired up correctly.")
    elif channel == "email":
        success, error = email_service.send_email(
            "Fire Sentinel Test Alert",
            "This is a test message confirming your email alert configuration works.",
        )
    else:
        return jsonify({"error": "channel must be 'telegram' or 'email'"}), 400

    return jsonify({"success": success, "error": error}), (200 if success else 502)
