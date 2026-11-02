"""
db.py — Ignis backend

Thin SQLite connection helper. Deliberately not an ORM: the schema is small
and stable enough that raw SQL in each route/service stays readable, and it
keeps the dependency list short for a student project. Connections are
opened per-request via Flask's `g` object and closed automatically.
"""

import sqlite3
import os
from flask import g
import config


def get_db():
    """Returns a sqlite3 connection scoped to the current request context."""
    if "db" not in g:
        g.db = sqlite3.connect(config.DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Creates the database file and applies schema.sql if not already applied.
    Safe to call on every startup — all CREATE statements use IF NOT EXISTS.
    """
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    os.makedirs(config.SNAPSHOT_STORAGE_DIR, exist_ok=True)

    conn = sqlite3.connect(config.DATABASE_PATH)
    with open(config.SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    _migrate(conn)
    conn.commit()
    conn.close()


# Columns added to `snapshots` after the first release. CREATE TABLE IF NOT EXISTS never alters an
# existing table, so an older database file gets them here. Keep in sync with schema.sql.
SNAPSHOT_EXTRA_COLUMNS = {
    "detector_status": "TEXT",
    "flame_count": "INTEGER",
    "flame_area_ratio": "REAL",
    "flame_boxes": "TEXT",
    "flame_growth": "REAL",
    "hazard_level": "TEXT",
    "hazard_reasons": "TEXT",
}


# Columns added to `sensor_readings` for firmware v2 telemetry (raw ADC counts for ML training, power monitor,
# window features, acknowledge counter). Keep in sync with schema.sql.
SENSOR_EXTRA_COLUMNS = {
    "mq2_raw": "INTEGER",
    "mq7_raw": "INTEGER",
    "mq135_raw": "INTEGER",
    "uv_raw": "INTEGER",
    "temp_rate_c_per_min": "REAL",
    "gas_agree_count": "INTEGER",
    "battery_pct": "INTEGER",
    "battery_v": "REAL",
    "bus_v": "REAL",
    "current_ma": "REAL",
    "power_mw": "REAL",
    "ack_seq": "INTEGER",
    "buzzer_silenced": "INTEGER",
    "sensor_fault": "INTEGER",
    "window_json": "TEXT",
    "ml_json": "TEXT",
}


def _add_missing_columns(conn, table, columns):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def _migrate(conn):
    _add_missing_columns(conn, "snapshots", SNAPSHOT_EXTRA_COLUMNS)
    _add_missing_columns(conn, "sensor_readings", SENSOR_EXTRA_COLUMNS)


def register_app(app):
    """Wires db teardown into the Flask app's lifecycle. Call from app.py."""
    app.teardown_appcontext(close_db)
