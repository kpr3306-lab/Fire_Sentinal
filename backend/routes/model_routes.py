"""
routes/model_routes.py — Ignis

Exposes whatever's in ml/cnn/model_manifest.json (once the ML phase produces
one) so the dashboard's AI/ML page and the device's hot-swap check can both
read model version/accuracy/size from one place. Returns a clearly-marked
placeholder until that file exists.
"""

import os
import json
from flask import Blueprint, jsonify

model_bp = Blueprint("model_routes", __name__)

MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..",
                             "ignis_ml_kit", "ml", "cnn", "model_manifest.json")


@model_bp.route("/api/model-info", methods=["GET"])
def model_info():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return jsonify(json.load(f)), 200

    return jsonify({
        "status": "not_trained_yet",
        "message": "No CNN model manifest found. This will populate once the ML phase produces "
                    "ml/cnn/model_manifest.json (version, accuracy, quantized size, input shape).",
    }), 200
