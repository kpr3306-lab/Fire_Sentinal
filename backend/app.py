"""
app.py — Fire Sentinel Prototype 2 backend entry point
"""

import os
from flask import Flask, jsonify
from flask_cors import CORS
import config
import db

from routes.device_routes import device_bp
from routes.sensor_routes import sensor_bp
from routes.camera_routes import camera_bp
from routes.events_routes import events_bp
from routes.profile_routes import profile_bp
from routes.alerts_routes import alerts_bp
from routes.model_routes import model_bp
from routes.dispatch_routes import dispatch_bp


def create_app():
    app = Flask(__name__)
    CORS(app)  # dashboard runs on a different port during development

    db.register_app(app)
    db.init_db()

    app.register_blueprint(device_bp)
    app.register_blueprint(sensor_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(model_bp)
    app.register_blueprint(dispatch_bp)

    # Countdown timer for the simulated fire-department dispatch: fires a due countdown even if the device
    # went silent. Skipped in the Flask reloader's parent process so it only runs where requests are served.
    if config.DISPATCH_ENABLED and (not config.DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        from services import dispatch_service
        dispatch_service.get_service().start_background(5)

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "fire-sentinel-backend"}), 200

    return app


if __name__ == "__main__":
    app = create_app()
    from services import yolo_service
    yolo_service.warm_up_async()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.DEBUG)
