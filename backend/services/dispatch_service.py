"""
Fire-department dispatch — SIMULATION (Ignis).

What it does
------------
When a device reports FIRE_CONFIRMED the service starts a human-in-the-loop countdown
(default 30 s). During the countdown the owner is told via Telegram and can cancel by
  * holding the info button on the device (firmware increments `ack_seq`), or
  * calling cancel() / POST /api/dispatch/cancel from the dashboard.
If nobody cancels, a SIMULATED dispatch is made: a message is sent to a separate
"Fire Dept (SIMULATED)" Telegram chat (or the normal chat with a [SIMULATION] banner) and
a row is written to the dispatch_events table so the dashboard can show the log.

It NEVER dials a real emergency number. (Blueprint safety note: an unverified automated
emergency call is a liability + false-alarm risk; a real deployment would ring a
pre-configured person or use a certified alarm-monitoring partner.)

Use get_service() everywhere; it wires the backend's own Telegram helper and SQLite file.
"""
import html
import sqlite3
from contextlib import contextmanager
import threading
import time
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS dispatch_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL,          -- countdown_started | cancelled | auto_cleared | rearmed | dispatched_sim
    detail      TEXT,
    risk_score  INTEGER,
    simulated   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
"""

IDLE, PENDING, CANCELLED, DISPATCHED = "idle", "pending", "cancelled", "dispatched"


class DispatchService:
    def __init__(self, db_path, notify_owner, notify_fire_dept_sim,
                 countdown_s=30, rearm_after_cancel_s=120, reset_after_normal_s=300,
                 clock=time.time):
        """
        notify_owner(text)          -> sends to your normal Telegram chat (use your existing helper)
        notify_fire_dept_sim(text, photo_path=None) -> sends to the SIM fire-dept chat (or same chat, prefixed)
        """
        self.db_path = db_path
        self.notify_owner = notify_owner
        self.notify_fire_dept_sim = notify_fire_dept_sim
        self.countdown_s = countdown_s
        self.rearm_after_cancel_s = rearm_after_cancel_s
        self.reset_after_normal_s = reset_after_normal_s
        self._clock = clock
        self._lock = threading.RLock()
        self._dev = {}                  # device_id -> runtime state
        self._stop = threading.Event()
        with self._db() as db:
            db.executescript(SCHEMA)

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _db(self):
        # sqlite3's own context manager commits but never closes; open handles lock the file on Windows
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _log(self, device_id, event_type, detail="", risk=None):
        with self._db() as db:
            db.execute(
                "INSERT INTO dispatch_events (device_id, event_type, detail, risk_score, simulated, created_at)"
                " VALUES (?,?,?,?,1,?)",
                (device_id, event_type, detail, risk, datetime.now(timezone.utc).isoformat()))
            # Also show it on the dashboard's Detection Timeline. 'ALERT_SENT' is an existing event type, so the
            # dashboard needs no change to display it.
            try:
                room = db.execute("SELECT room_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
                db.execute(
                    "INSERT INTO events (device_id, room_id, event_type, to_state, risk_score, message) VALUES (?,?,?,?,?,?)",
                    (device_id, room["room_id"] if room else None, "ALERT_SENT", "FIRE_CONFIRMED", risk,
                     f"Dispatch (simulated): {event_type.replace('_', ' ')}" + (f" — {detail}" if detail else "")))
            except sqlite3.Error as exc:
                print(f"[dispatch] timeline log failed: {exc}")

    def _st(self, device_id):
        return self._dev.setdefault(device_id, {
            "phase": IDLE, "since": 0.0, "last_ack_seq": None,
            "normal_since": None, "risk": 0, "context": {}})

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception as exc:        # a Telegram outage must never break ingestion
            print(f"[dispatch] notify failed: {exc}")

    # ------------------------------------------------------------------ public API
    def on_reading(self, device_id, state, risk_score=0, ack_seq=None, context=None):
        """Call from POST /api/sensor-data after the reading is stored. Returns an event name or None."""
        now = self._clock()
        with self._lock:
            s = self._st(device_id)
            s["risk"] = risk_score
            if context:
                s["context"] = context

            ack_event = False
            if ack_seq is not None:
                last = s["last_ack_seq"]
                if last is not None and ack_seq > last:
                    ack_event = True
                s["last_ack_seq"] = ack_seq     # seeds on first reading; reseeds after a device reboot

            return self._step(device_id, s, state, now, ack_event)

    def tick(self):
        """Fires due countdowns even if the device stopped reporting (e.g. WiFi died mid-fire)."""
        now = self._clock()
        with self._lock:
            for device_id, s in self._dev.items():
                if s["phase"] == PENDING and now - s["since"] >= self.countdown_s:
                    self._dispatch(device_id, s, now)

    def cancel(self, device_id, source="dashboard"):
        with self._lock:
            s = self._st(device_id)
            if s["phase"] != PENDING:
                return False
            self._to_cancelled(device_id, s, self._clock(), source)
            return True

    def status(self, device_id):
        with self._lock:
            s = self._st(device_id)
            remaining = max(0, int(self.countdown_s - (self._clock() - s["since"]))) if s["phase"] == PENDING else None
            return {"phase": s["phase"], "seconds_remaining": remaining}

    def events(self, limit=50):
        with self._db() as db:
            rows = db.execute("SELECT * FROM dispatch_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def start_background(self, interval_s=5):
        def loop():
            while not self._stop.wait(interval_s):
                self.tick()
        threading.Thread(target=loop, daemon=True, name="dispatch-tick").start()

    def stop_background(self):
        self._stop.set()

    # ------------------------------------------------------------------ state machine
    def _step(self, device_id, s, state, now, ack_event):
        phase = s["phase"]

        # track "calm" time so a finished episode eventually resets
        if state == "NORMAL":
            s["normal_since"] = s["normal_since"] or now
        else:
            s["normal_since"] = None

        if phase == IDLE:
            if state == "FIRE_CONFIRMED":
                s.update(phase=PENDING, since=now)
                self._log(device_id, "countdown_started", f"{self.countdown_s}s", s["risk"])
                self._safe(self.notify_owner,
                    f"🔥 FIRE_CONFIRMED on {self._where(s)} (risk {s['risk']}/100).\n"
                    f"SIMULATED fire-department dispatch in {self.countdown_s} s.\n"
                    f"Cancel: hold the info button on the device (1.5 s) or use the dashboard.")
                return "countdown_started"
            return None

        if phase == PENDING:
            if ack_event:
                self._to_cancelled(device_id, s, now, "device button")
                return "cancelled"
            if state in ("NORMAL", "PRECURSOR"):
                s["phase"] = IDLE
                self._log(device_id, "auto_cleared", f"state fell to {state}", s["risk"])
                self._safe(self.notify_owner, f"✅ Dispatch countdown cleared automatically — {self._where(s)} is back to {state}.")
                return "auto_cleared"
            if now - s["since"] >= self.countdown_s:
                self._dispatch(device_id, s, now)
                return "dispatched_sim"
            return None

        if phase == CANCELLED:
            if state == "FIRE_CONFIRMED" and now - s["since"] >= self.rearm_after_cancel_s:
                s.update(phase=PENDING, since=now)
                self._log(device_id, "rearmed", "still FIRE_CONFIRMED after cancel", s["risk"])
                self._safe(self.notify_owner,
                    f"⚠️ Still FIRE_CONFIRMED on {self._where(s)} {self.rearm_after_cancel_s}s after cancel — "
                    f"dispatch countdown restarted ({self.countdown_s} s).")
                return "rearmed"
            if s["normal_since"] and now - s["normal_since"] >= self.reset_after_normal_s:
                s["phase"] = IDLE
            return None

        if phase == DISPATCHED:
            if s["normal_since"] and now - s["normal_since"] >= self.reset_after_normal_s:
                s["phase"] = IDLE
            return None
        return None

    def _to_cancelled(self, device_id, s, now, source):
        s.update(phase=CANCELLED, since=now)
        self._log(device_id, "cancelled", f"by {source}", s["risk"])
        self._safe(self.notify_owner, f"🛑 Dispatch countdown cancelled ({source}) on {self._where(s)}.")

    def _dispatch(self, device_id, s, now):
        s.update(phase=DISPATCHED, since=now)
        ctx = s["context"]
        msg = (
            "🚒 [SIMULATION — no real call was placed]\n"
            "FIRE DEPARTMENT DISPATCH REQUEST\n"
            f"Location : {self._where(s)}\n"
            f"Device   : {html.escape(str(device_id))}\n"
            f"Risk     : {s['risk']}/100 (FIRE_CONFIRMED)\n"
            f"Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            + (f"Camera   : {html.escape(str(ctx['classification']))}, flame hazard {html.escape(str(ctx.get('hazard_level') or 'n/a'))}\n" if ctx.get("classification") else "")
            + (f"Evidence : {ctx['snapshot_url']}\n" if ctx.get("snapshot_url") else "")
            + (f"Dashboard: {ctx['dashboard_url']}\n" if ctx.get("dashboard_url") else ""))
        self._safe(self.notify_fire_dept_sim, msg, ctx.get("snapshot_path"))
        self._log(device_id, "dispatched_sim", "simulated message sent", s["risk"])
        self._safe(self.notify_owner, f"🚒 SIMULATED dispatch sent for {self._where(s)}. (No real emergency call was made.)")

    @staticmethod
    def _where(s):
        c = s["context"]
        return html.escape(str(c.get("room") or c.get("address") or "the monitored room"))


# ----------------------------------------------------------------------------------------------
# Singleton wired to this backend's own config + Telegram helper
# ----------------------------------------------------------------------------------------------
_service = None
_service_lock = threading.Lock()


def _notify_owner(text):
    from services import telegram_service
    telegram_service.send_text(text)


def _notify_fire_dept_sim(text, photo_path=None):
    import os
    from services import telegram_service
    chat = config.TELEGRAM_FIRE_DEPT_SIM_CHAT_ID or None
    if photo_path and os.path.exists(photo_path):
        telegram_service.send_photo(text, photo_path, chat_id=chat)
    else:
        telegram_service.send_text(text, chat_id=chat)


def get_service(clock=None):
    """The one DispatchService for this process. `clock` is only honoured on first creation (tests)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = DispatchService(
                db_path=config.DATABASE_PATH,
                notify_owner=_notify_owner,
                notify_fire_dept_sim=_notify_fire_dept_sim,
                countdown_s=config.DISPATCH_COUNTDOWN_S,
                rearm_after_cancel_s=config.DISPATCH_REARM_AFTER_CANCEL_S,
                reset_after_normal_s=config.DISPATCH_RESET_AFTER_NORMAL_S,
                **({"clock": clock} if clock else {}))
        return _service


def reset_service():
    """Tests only: drop the singleton so the next get_service() rebuilds it."""
    global _service
    with _service_lock:
        if _service is not None:
            _service.stop_background()
        _service = None
