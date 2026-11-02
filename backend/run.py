"""
run.py — convenience entry point (`python run.py`), identical to running
app.py directly. Kept separate so app.py can be imported (e.g. by tests or
a WSGI server) without triggering app.run().
"""

from app import create_app
import config

if __name__ == "__main__":
    app = create_app()
    from services import yolo_service
    yolo_service.warm_up_async()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.DEBUG)
