"""
routes/dispatch_routes.py — Fire Sentinel

Dashboard-facing API for the SIMULATED fire-department dispatch (services/dispatch_service.py).

  GET  /api/dispatch/status?device_id=...   -> {"phase": idle|pending|cancelled|dispatched, "seconds_remaining": n|null}
  POST /api/dispatch/cancel                  body {"device_id": "..."}  (dashboard cancel button)
  GET  /api/dispatch/events?limit=50         -> dispatch log (countdown_started / cancelled / dispatched_sim ...)
"""

from flask import Blueprint, request, jsonify
from services import dispatch_service

dispatch_bp = Blueprint("dispatch_routes", __name__)


@dispatch_bp.route("/api/dispatch/status", methods=["GET"])
def dispatch_status():
    device_id = request.args.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id query param required"}), 400
    return jsonify({**dispatch_service.get_service().status(device_id), "simulated": True}), 200


@dispatch_bp.route("/api/dispatch/cancel", methods=["POST"])
def dispatch_cancel():
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id is required"}), 400
    cancelled = dispatch_service.get_service().cancel(device_id, source="dashboard")
    return jsonify({"cancelled": cancelled}), 200


@dispatch_bp.route("/api/dispatch/events", methods=["GET"])
def dispatch_events():
    limit = int(request.args.get("limit", 50))
    return jsonify(dispatch_service.get_service().events(limit)), 200
