# Ignis — Backend

Flask + raw SQLite (no ORM — schema is small and stable enough that plain
SQL stays readable, keeps dependencies light).

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp env.example .env               # then fill in Telegram/Gmail credentials
python run.py
```

Server starts on `http://0.0.0.0:5000`. The database file and schema are
created automatically on first run — nothing to migrate by hand.

## Configuring alerts

- **Telegram**: message @BotFather to create a bot and get `TELEGRAM_BOT_TOKEN`,
  then message @userinfobot to get your `TELEGRAM_CHAT_ID`.
- **Email**: enable 2-Step Verification on the sending Gmail account, then
  create an App Password (Google Account → Security → App Passwords). Use
  that as `EMAIL_APP_PASSWORD`, not your normal Gmail password.

Test both before your firmware is even talking to the backend:
```bash
curl -X POST http://localhost:5000/api/alerts/test -H "Content-Type: application/json" -d '{"channel":"telegram"}'
curl -X POST http://localhost:5000/api/alerts/test -H "Content-Type: application/json" -d '{"channel":"email"}'
```

## Alert severity tiers (config.py → ALERT_POLICY)
| State | Telegram | Email | Severity |
|---|---|---|---|
| PRECURSOR | ✅ | ❌ | info |
| CONFIRMING | ✅ | ✅ | warning |
| FIRE_CONFIRMED | ✅ | ✅ | critical |

Fully editable in `config.py` — nothing else needs to change if you retune these.

## API reference

### Device registry (solves the "no reflash to change room/IP" requirement)
- `POST /api/device/register` — device self-announces (called by firmware)
- `GET  /api/devices` — list all known devices
- `GET  /api/devices/<device_id>` — one device's current address/state
- `PUT  /api/devices/<device_id>/room` — assign device to a room, dashboard-side
- `PUT  /api/devices/<device_id>/override` — pin a manual IP/port, or clear it

### Sensor data
- `POST /api/sensor-data` — ingestion endpoint (called by firmware)
- `GET  /api/sensor-data/latest?device_id=...` — live gauge tile data
- `GET  /api/sensor-data/history?device_id=...&limit=50` — trend chart data

### Camera / snapshots
- `POST /api/camera/snapshot` — snapshot upload (called by firmware, any reason)
- `GET  /api/camera/capture-proxy?device_id=...` — dashboard "Turn On" button hits this
- `GET  /api/camera/snapshots?device_id=...&limit=50` — gallery listing
- `GET  /api/camera/snapshots/<id>/file` — serves the actual JPEG

### Events / timeline
- `GET /api/events?room_id=...&limit=50` — Detection Timeline
- `GET /api/events/recent?limit=10` — Recent Events sidebar

### Profile
- `GET/POST /api/rooms`, `DELETE /api/rooms/<id>`
- `GET/POST /api/rooms/<room_id>/appliances`, `DELETE /api/appliances/<id>`
- `GET/POST /api/contacts`, `DELETE /api/contacts/<id>`

### Alerts / model
- `GET /api/alerts/history?limit=50`
- `POST /api/alerts/test` — `{"channel": "telegram"|"email"}`
- `GET /api/model-info` — CNN manifest (placeholder until ML phase)

## What's stubbed, on purpose, for now
- **`services/ml_inference_service.py`** — `classify_snapshot()` always
  returns `PENDING_MODEL` until the ML phase wires in the trained MobileNetV2
  model. Every snapshot still saves and displays correctly in the meantime;
  only the `classification` field is a placeholder.
- **`services/gas_pattern_service.py`** — the "which gas is building up" hint
  is currently rule-based (compares relative deviation across MQ-2/7/135).
  Gets upgraded to a trained pattern classifier once you've logged labeled
  gas-source trial sessions — the function signature won't change, so nothing
  calling it needs updating later.
- **Twilio emergency calling** — not wired in yet; Telegram + email only for
  now, per this session's scope. Add as `services/twilio_service.py` +
  `ALERT_POLICY` extension when you're ready for it.

## A note on the server-side gas-source baseline
`risk_score_service.py` computes its own rolling baseline from each device's
last 60 NORMAL-state readings, independently of the firmware's own on-device
baseline. This isn't redundant — it gives the backend a longer memory (the
device's baseline resets on reboot) and is what backs the gas-source hint.
It needs at least 5 NORMAL-state samples logged before it produces a hint;
before that, `/api/sensor-data` responses say so explicitly rather than
guessing from insufficient data.
