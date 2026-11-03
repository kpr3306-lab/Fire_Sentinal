"""
config.py — Fire Sentinel backend

Secrets (Telegram bot token, email credentials) are read from environment
variables, loaded from a local .env file via python-dotenv. Copy .env.example
to .env and fill in your own values — .env should never be committed.
"""

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_PATH = os.path.join(BASE_DIR, "database", "fire_sentinel.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")

# ---------------------------------------------------------------------------
# Snapshot storage
# ---------------------------------------------------------------------------
SNAPSHOT_STORAGE_DIR = os.path.join(BASE_DIR, "storage", "snapshots")

# ---------------------------------------------------------------------------
# YOLO flame detector (services/yolo_service.py) — optional.
# If the weights file is missing or ultralytics is not installed, snapshots are
# still saved and classified; the detector just reports status "unavailable".
# ---------------------------------------------------------------------------
YOLO_MODEL_PATH = os.getenv("FIRE_YOLO_PATH", os.path.join(BASE_DIR, "models", "fire_yolo.pt"))
YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF", "0.25"))   # pick from ml/yolo/artifacts/colab_run BoxF1_curve.png
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))

# ---------------------------------------------------------------------------
# Hazard logic (services/hazard_service.py).
# !! PLACEHOLDER VALUES — NOT CALIBRATED. !!  They are rough guesses from the
# training-set box sizes (stove flames: 90th percentile about 6% of the frame).
# Tune them on real OV3660 footage: a small stable flame vs a spreading one.
# ---------------------------------------------------------------------------
HAZARD_AREA_RATIO = float(os.getenv("HAZARD_AREA_RATIO", "0.15"))     # flame covers >= this share of frame -> hazardous
HAZARD_GROWTH_RATIO = float(os.getenv("HAZARD_GROWTH_RATIO", "1.5"))  # area now / area in previous snapshot
HAZARD_GROWTH_MIN_AREA = float(os.getenv("HAZARD_GROWTH_MIN_AREA", "0.01"))  # ignore growth of specks below this share
HAZARD_GROWTH_WINDOW_S = int(os.getenv("HAZARD_GROWTH_WINDOW_S", "180"))     # only compare with a snapshot this recent

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Optional second chat that plays the role of the fire department's dispatch desk (SIMULATION).
# Create a Telegram group "Fire Dept (SIM)", add the bot, and put that chat id here. If empty, the
# simulated dispatch goes to the normal chat with a [SIMULATION] banner.
TELEGRAM_FIRE_DEPT_SIM_CHAT_ID = os.getenv("TELEGRAM_FIRE_DEPT_SIM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Email (Gmail SMTP, matching Prototype 1)
# ---------------------------------------------------------------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")   # Gmail App Password, not your login password
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")
EMAIL_SMTP_HOST = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
EMAIL_ENABLED = bool(EMAIL_SENDER and EMAIL_APP_PASSWORD and EMAIL_RECIPIENT)

# ---------------------------------------------------------------------------
# Alert severity tiers by fire state.
# Tune this freely — it's read by services/risk_score_service.py, nothing
# else needs to change if you adjust tiers.
# ---------------------------------------------------------------------------
ALERT_POLICY = {
    "NORMAL":         {"telegram": False, "email": False, "severity": None},
    "PRECURSOR":      {"telegram": True,  "email": False, "severity": "info"},
    "CONFIRMING":     {"telegram": True,  "email": True,  "severity": "warning"},
    "FIRE_CONFIRMED": {"telegram": True,  "email": True,  "severity": "critical"},
}

# ---------------------------------------------------------------------------
# Fire-department dispatch (services/dispatch_service.py) — SIMULATION ONLY.
# On FIRE_CONFIRMED a human-in-the-loop countdown starts; it is cancelled by holding the device's info
# button (firmware ack_seq) or by POST /api/dispatch/cancel. If nobody cancels, a SIMULATED dispatch
# message is sent. This never places a real emergency call.
# ---------------------------------------------------------------------------
DISPATCH_ENABLED = os.getenv("DISPATCH_ENABLED", "1") == "1"
DISPATCH_COUNTDOWN_S = int(os.getenv("DISPATCH_COUNTDOWN_S", "30"))
DISPATCH_REARM_AFTER_CANCEL_S = int(os.getenv("DISPATCH_REARM_AFTER_CANCEL_S", "120"))   # still FIRE_CONFIRMED this long after a cancel -> countdown restarts
DISPATCH_RESET_AFTER_NORMAL_S = int(os.getenv("DISPATCH_RESET_AFTER_NORMAL_S", "300"))
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:5173")
PUBLIC_BACKEND_URL = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:5000")             # use your LAN IP so snapshot links open on your phone

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
DEBUG = True
