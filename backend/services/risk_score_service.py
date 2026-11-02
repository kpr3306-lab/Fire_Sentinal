"""
services/risk_score_service.py — Fire Sentinel Prototype 2

This is the orchestration layer that runs every time a sensor reading comes
in from a device. It:
  1. Computes a server-side gas-deviation baseline from this device's own
     recent NORMAL-state history (independent of the firmware's own
     on-device baseline — a second, longer-memory check).
  2. Gets the rule-based gas-source hint from gas_pattern_service.
  3. Detects state transitions (compares incoming state to the device's
     last known state in the DB) and logs a STATE_CHANGE event.
  4. Dispatches Telegram/email alerts per config.ALERT_POLICY, opportunistically
     attaching the most recent snapshot for this device if one landed within
     the last ALERT_SNAPSHOT_WINDOW_SECONDS.

Kept as plain functions taking a `conn` (sqlite3 connection) rather than
importing db.get_db() directly, so this is testable outside a Flask request
context if needed later.
"""

import time
import os
import json
import config
from services import gas_pattern_service, telegram_service, email_service, dispatch_service

ALERT_SNAPSHOT_WINDOW_SECONDS = 30
BASELINE_HISTORY_LIMIT = 60
BASELINE_MIN_SAMPLES = 5


def _get_server_side_baseline(conn, device_id):
    rows = conn.execute(
        """SELECT mq2_ppm, mq7_ppm, mq135_ppm FROM sensor_readings
           WHERE device_id = ? AND state = 'NORMAL'
           ORDER BY created_at DESC LIMIT ?""",
        (device_id, BASELINE_HISTORY_LIMIT),
    ).fetchall()

    if len(rows) < BASELINE_MIN_SAMPLES:
        return None

    def avg(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return sum(vals) / len(vals) if vals else 0.0

    return {"mq2": avg("mq2_ppm"), "mq7": avg("mq7_ppm"), "mq135": avg("mq135_ppm")}


def _deviation_pct(current, baseline):
    if baseline is None or baseline <= 1.0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def _find_recent_snapshot_path(conn, device_id):
    row = conn.execute(
        """SELECT file_path, created_at FROM snapshots
           WHERE device_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (device_id,),
    ).fetchone()

    if row is None:
        return None

    # created_at is TEXT in sqlite's default TIMESTAMP format; compare loosely
    # by re-querying with a time filter instead of parsing strings by hand.
    recent = conn.execute(
        """SELECT file_path FROM snapshots
           WHERE device_id = ?
             AND created_at >= datetime('now', ?)
           ORDER BY created_at DESC LIMIT 1""",
        (device_id, f"-{ALERT_SNAPSHOT_WINDOW_SECONDS} seconds"),
    ).fetchone()

    return recent["file_path"] if recent else None


def _dispatch_context(conn, device_id, room_id):
    """Room name + newest snapshot details, handed to the simulated fire-department dispatch."""
    ctx = {"dashboard_url": config.DASHBOARD_URL}
    if room_id is not None:
        row = conn.execute("SELECT name FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if row:
            ctx["room"] = row["name"]
    snap = conn.execute(
        """SELECT id, file_path, classification, hazard_level FROM snapshots
           WHERE device_id = ? ORDER BY id DESC LIMIT 1""", (device_id,)).fetchone()
    if snap:
        ctx.update(snapshot_path=snap["file_path"], classification=snap["classification"],
                   hazard_level=snap["hazard_level"],
                   snapshot_url=f"{config.PUBLIC_BACKEND_URL}/api/camera/snapshots/{snap['id']}/file")
    return ctx


def _dispatch_alert(conn, device_id, room_id, to_state, message, photo_path):
    policy = config.ALERT_POLICY.get(to_state)
    if policy is None or policy["severity"] is None:
        return

    if policy["telegram"]:
        if photo_path and os.path.exists(photo_path):
            success, error = telegram_service.send_photo(message, photo_path)
        else:
            success, error = telegram_service.send_text(message)
        conn.execute(
            """INSERT INTO alerts (device_id, room_id, channel, severity, message, success, error_detail)
               VALUES (?, ?, 'telegram', ?, ?, ?, ?)""",
            (device_id, room_id, policy["severity"], message, int(success), error),
        )

    if policy["email"]:
        subject = f"Fire Sentinel Alert [{policy['severity'].upper()}] — {to_state}"
        success, error = email_service.send_email(subject, message, attachment_path=photo_path)
        conn.execute(
            """INSERT INTO alerts (device_id, room_id, channel, severity, message, success, error_detail)
               VALUES (?, ?, 'email', ?, ?, ?, ?)""",
            (device_id, room_id, policy["severity"], message, int(success), error),
        )

    conn.commit()


def process_sensor_reading(conn, payload: dict) -> dict:
    device_id = payload["device_id"]
    incoming_state = payload.get("state", "NORMAL")
    risk_score = payload.get("risk_score", 0)
    sensors = payload.get("sensors", {})
    fusion = payload.get("fusion", {})

    # A reading can arrive before the device's registration call lands; create a bare row so the
    # foreign key on sensor_readings does not reject it (registration fills in the rest later).
    conn.execute("INSERT OR IGNORE INTO devices (device_id) VALUES (?)", (device_id,))

    device_row = conn.execute(
        "SELECT room_id, last_state FROM devices WHERE device_id = ?", (device_id,)
    ).fetchone()
    room_id = device_row["room_id"] if device_row else None
    last_state = device_row["last_state"] if device_row else "NORMAL"

    # --- Server-side gas-source hint (independent long-memory baseline) ---
    baseline = _get_server_side_baseline(conn, device_id)
    if baseline:
        dev2 = _deviation_pct(sensors.get("mq2_ppm", 0), baseline["mq2"])
        dev7 = _deviation_pct(sensors.get("mq7_ppm", 0), baseline["mq7"])
        dev135 = _deviation_pct(sensors.get("mq135_ppm", 0), baseline["mq135"])
        hint = gas_pattern_service.infer_gas_source_hint(dev2, dev7, dev135)
    else:
        hint = gas_pattern_service.GasSourceHint(
            label="Insufficient history for a gas-source hint yet",
            dominant_sensor="none",
            confidence_note=f"Needs at least {BASELINE_MIN_SAMPLES} NORMAL-state samples logged first.",
        )

    # --- Insert the raw reading ---
    power = payload.get("power") or {}
    window = payload.get("window")
    ml = payload.get("ml")
    row = {
        "device_id": device_id, "room_id": room_id, "timestamp_ms": payload.get("timestamp_ms"),
        "state": incoming_state, "risk_score": risk_score,
        "temperature_c": sensors.get("temperature_c"), "humidity_pct": sensors.get("humidity_pct"),
        "pressure_hpa": sensors.get("pressure_hpa"),
        "mq2_ppm": sensors.get("mq2_ppm"), "mq7_ppm": sensors.get("mq7_ppm"),
        "mq135_ppm": sensors.get("mq135_ppm"), "uv_index": sensors.get("uv_index"),
        "flame_detected": int(sensors.get("flame_detected", False)),
        "reading_valid": int(sensors.get("reading_valid", True)),
        "temp_deviation": fusion.get("temp_deviation", 0), "gas_deviation_pct": fusion.get("gas_deviation_pct", 0),
        "gas_source_hint": hint.label,
        # firmware v2 telemetry (all optional — older firmware simply leaves these NULL)
        "mq2_raw": sensors.get("mq2_raw"), "mq7_raw": sensors.get("mq7_raw"),
        "mq135_raw": sensors.get("mq135_raw"), "uv_raw": sensors.get("uv_raw"),
        "temp_rate_c_per_min": fusion.get("temp_rate_c_per_min"), "gas_agree_count": fusion.get("gas_agree_count"),
        "battery_pct": power.get("battery_pct"), "battery_v": power.get("battery_v"),
        "bus_v": power.get("bus_v"), "current_ma": power.get("current_ma"), "power_mw": power.get("power_mw"),
        "ack_seq": payload.get("ack_seq"),
        "buzzer_silenced": int(payload["buzzer_silenced"]) if "buzzer_silenced" in payload else None,
        "sensor_fault": int(payload["sensor_fault"]) if "sensor_fault" in payload else None,
        "window_json": json.dumps(window) if window else None,
        "ml_json": json.dumps(ml) if ml else None,
    }
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO sensor_readings ({columns}) VALUES ({placeholders})", tuple(row.values()))

    # --- Upsert device bookkeeping ---
    conn.execute(
        """UPDATE devices SET last_state = ?, last_seen_at = CURRENT_TIMESTAMP WHERE device_id = ?""",
        (incoming_state, device_id),
    )
    conn.commit()

    state_changed = incoming_state != last_state
    if state_changed:
        conn.execute(
            """INSERT INTO events (device_id, room_id, event_type, from_state, to_state, risk_score, message)
               VALUES (?, ?, 'STATE_CHANGE', ?, ?, ?, ?)""",
            (device_id, room_id, last_state, incoming_state, risk_score,
             f"State changed from {last_state} to {incoming_state} (risk score {risk_score})"),
        )
        conn.commit()

        message = (
            f"Fire Sentinel — {incoming_state.replace('_', ' ')}\n"
            f"Device: {device_id}\n"
            f"Risk score: {risk_score}/100\n"
            f"Temp: {sensors.get('temperature_c', '?')}°C | "
            f"MQ2: {sensors.get('mq2_ppm', '?')}ppm | MQ7: {sensors.get('mq7_ppm', '?')}ppm | "
            f"MQ135: {sensors.get('mq135_ppm', '?')}ppm\n"
            f"Gas hint: {hint.label}"
        )
        photo_path = _find_recent_snapshot_path(conn, device_id)
        _dispatch_alert(conn, device_id, room_id, incoming_state, message, photo_path)

    # --- Simulated fire-department dispatch (countdown / cancel / dispatch). Never allowed to break ingestion. ---
    dispatch_event = None
    if config.DISPATCH_ENABLED:
        try:
            ctx = _dispatch_context(conn, device_id, room_id) if incoming_state in ("CONFIRMING", "FIRE_CONFIRMED") else None
            dispatch_event = dispatch_service.get_service().on_reading(
                device_id, incoming_state, risk_score, ack_seq=payload.get("ack_seq"), context=ctx)
        except Exception as exc:
            print(f"[dispatch] on_reading failed: {exc}")

    return {
        "state_changed": state_changed,
        "gas_source_hint": hint.label,
        "gas_hint_confidence_note": hint.confidence_note,
        "dispatch_event": dispatch_event,
    }
