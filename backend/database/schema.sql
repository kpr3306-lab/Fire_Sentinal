-- Fire Sentinel — SQLite schema
-- Run automatically by db.init_db() on first launch if fire_sentinel.db doesn't exist.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Rooms — the unit dashboards/alerts are organized around. Devices are
-- assigned to a room from the dashboard, NOT baked into firmware.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rooms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Devices — self-registered by the ESP32-S3 on boot. ip/port are whatever the
-- device last announced; ip_override/port_override let the dashboard pin a
-- fixed address if the user wants to bypass auto-discovery.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT PRIMARY KEY,
    device_name     TEXT,
    room_id         INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    ip              TEXT,
    port            INTEGER,
    ip_override     TEXT,
    port_override   INTEGER,
    use_override    INTEGER DEFAULT 0,
    rssi            INTEGER,
    last_state      TEXT DEFAULT 'NORMAL',
    last_seen_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Sensor readings — one row per POST /api/sensor-data. This is the raw
-- telemetry feed backing the live gauges and trend charts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_readings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id         TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    room_id           INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    timestamp_ms      INTEGER,
    state             TEXT,
    risk_score        INTEGER,
    temperature_c     REAL,
    humidity_pct      REAL,
    pressure_hpa      REAL,
    mq2_ppm           REAL,
    mq7_ppm           REAL,
    mq135_ppm         REAL,
    uv_index          REAL,
    flame_detected    INTEGER,
    reading_valid     INTEGER,
    temp_deviation    REAL,
    gas_deviation_pct REAL,
    gas_source_hint   TEXT,     -- rule-based (later ML-based) "likely gas source" label
    -- Firmware v2 telemetry. NOTE: db.py also adds these to an existing database (ALTER TABLE) — keep both lists in sync.
    mq2_raw           INTEGER,  -- raw ADS1115 counts (train the sensor model on these, not the placeholder *_ppm)
    mq7_raw           INTEGER,
    mq135_raw         INTEGER,
    uv_raw            INTEGER,
    temp_rate_c_per_min REAL,
    gas_agree_count   INTEGER,
    battery_pct       INTEGER,  -- -1 = unavailable (INA219 still on the 5V side)
    battery_v         REAL,
    bus_v             REAL,
    current_ma        REAL,
    power_mw          REAL,
    ack_seq           INTEGER,  -- +1 per info-button long press while elevated (cancels the dispatch countdown)
    buzzer_silenced   INTEGER,
    sensor_fault      INTEGER,
    window_json       TEXT,     -- 30 s window features (mean/std/slope per channel), JSON
    ml_json           TEXT,     -- on-device sensor-model output (class / confidence / anomaly score), JSON
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_device_time
    ON sensor_readings(device_id, created_at);

-- ---------------------------------------------------------------------------
-- Events — state transitions, worth showing on the Detection Timeline.
-- Distinct from raw sensor_readings: this is "what happened", not every
-- individual sample.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    room_id       INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    event_type    TEXT,     -- STATE_CHANGE | SNAPSHOT_CAPTURED | ALERT_SENT
    from_state    TEXT,
    to_state      TEXT,
    risk_score    INTEGER,
    message       TEXT,
    snapshot_id   INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_room_time ON events(room_id, created_at);

-- ---------------------------------------------------------------------------
-- Snapshots — every uploaded image, regardless of severity. Per requirement:
-- ANY time the camera turns on, the snapshot is saved and stays browsable,
-- even for controlled-flame / on-demand / informational captures.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    room_id         INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    reason          TEXT,     -- precursor | confirming | fire_confirmed | on_demand
    file_path       TEXT NOT NULL,
    classification  TEXT DEFAULT 'PENDING_MODEL',  -- filled in once the CNN phase lands
    confidence      REAL,
    -- YOLO flame detector + hazard logic (NULL on rows saved before this feature).
    -- NOTE: db.py also adds these columns to an existing database (ALTER TABLE) — keep both lists in sync.
    detector_status TEXT,     -- ok | unavailable | error   ('unavailable' = nothing was detected because the detector was off, NOT because there is no fire)
    flame_count     INTEGER,
    flame_area_ratio REAL,    -- union of flame boxes as a share of the frame (0-1); NULL unless detector_status = ok
    flame_boxes     TEXT,     -- JSON list of [x1,y1,x2,y2,conf], coordinates normalised 0-1
    flame_growth    REAL,     -- area now / area in previous snapshot from the same device (NULL if no comparable previous)
    hazard_level    TEXT,     -- NONE | CONTROLLED | HAZARDOUS | UNKNOWN
    hazard_reasons  TEXT,     -- JSON list of short human-readable reasons
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_device_time ON snapshots(device_id, created_at);

-- ---------------------------------------------------------------------------
-- Room appliances — user-declared electrical/gas equipment per room. Used as
-- a minor contextual prior in risk scoring and surfaced in incident reports
-- as a possible-contributing-factor hint, never an auto-diagnosis.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS appliances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    category    TEXT CHECK(category IN ('electrical', 'gas')) NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Emergency contacts — shown on the dashboard's Emergency Contacts panel.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emergency_contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL,
    relation    TEXT,          -- e.g. "Fire Department", "Family"
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Alert log — every Telegram/email send attempt, for the Alerts history page
-- and for debugging delivery failures.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    room_id       INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    channel       TEXT,       -- telegram | email
    severity      TEXT,       -- info | warning | critical
    message       TEXT,
    success       INTEGER,
    error_detail  TEXT,
    sent_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Dispatch log — SIMULATED fire-department dispatch + countdown/cancel history.
-- (services/dispatch_service.py also creates this table itself if it is missing.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dispatch_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL,      -- countdown_started | cancelled | auto_cleared | rearmed | dispatched_sim
    detail      TEXT,
    risk_score  INTEGER,
    simulated   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
