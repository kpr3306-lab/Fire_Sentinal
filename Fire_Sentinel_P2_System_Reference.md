# Fire Sentinel — Prototype 2: Complete System Reference

Updated wiring · how every part works · what every file is for
(State of the project as of 29 Oct 2026 — firmware v2.3: on-device CNN + YOLO from microSD, USB-C power)

> **29 Oct 2026 update (v2.3).** Battery, TP4056, boost converter and INA219 removed: the board runs from a USB-C 5 V supply. The firmware loads the quantized CNN and YOLO from the microSD root and classifies every snapshot on the board (`vision.cpp`). Backend IP is `10.111.193.119`. Flashing steps: `firmware/README_FLASHING.md`. Sections below that mention the INA219, battery % or the POWER screen describe v2.2.

---

## Contents
1. [Status snapshot — what is done, what is not](#1-status-snapshot)
2. [System at a glance](#2-system-at-a-glance)
3. [Hardware and wiring (updated)](#3-hardware-and-wiring-updated)
4. [Firmware (v2.2) — how it works](#4-firmware-v22--how-it-works)
5. [Firmware — purpose of every file](#5-firmware--purpose-of-every-file)
6. [Backend (Flask + SQLite)](#6-backend-flask--sqlite)
7. [ML — CNN, YOLO, sensor model](#7-ml--cnn-yolo-sensor-model)
8. [Dashboard (React)](#8-dashboard-react)
9. [End-to-end walk-throughs](#9-end-to-end-walk-throughs)
10. [Testing and verification status](#10-testing-and-verification-status)
11. [Known limitations and open items](#11-known-limitations-and-open-items)
12. [Quick reference](#12-quick-reference)

---

## 1. Status snapshot

| Area | State |
|---|---|
| Hardware wiring | Done (LEDs and diffuse button removed from the design) |
| Firmware v2.3 | Compiles with the real esp32 core 3.3.12 (needs ArduinoJson 7). **Not yet run on the board.** |
| Backend | Existing 20-file Flask backend + new patch (simulated dispatch, new telemetry). 29 unit/integration tests pass. |
| Dashboard | Delivered earlier (React/Vite/Tailwind). **No panel yet for the dispatch countdown/cancel.** |
| CNN (3-class MobileNetV2, INT8) | Trained and quantized (INT8 acc 96.98 %, hazardous recall 91.92 %). Runs on the board from the microSD (`vision.cpp`). |
| YOLO11n (flame boxes) | `fire_yolo_int8_160.tflite` runs on the board from the microSD. Secondary signal only. |
| Backend CNN inference | Backend stub stays; the snapshot upload carries the board's CNN class + YOLO boxes, which the backend stores when its own models are absent. |
| Sensor model (RF + anomaly) | Kit written and tested on **synthetic** data. **No real sessions recorded yet**, so the firmware ships with a stub model (rule-based only). |
| Telegram / Email | Backend sends them on state change. Check `.env` — the copy sent had empty values. |
| Fire-department alert | **Simulation only**, by design. No real emergency call is ever placed. |
| Twilio call escalation | Planned, not built. |

---

## 2. System at a glance

```
                        ┌──────────────────────── ESP32-S3 (one board) ─────────────────────────┐
  BME280 ─┐             │  loop() core 1                         net task core 0                 │
  ADS1115 ─┼─ I2C ───►  │  sensors @1 Hz → window → baseline     queue ◄── jobs from loop()      │
  INA219 ─┤  (20/21)    │  → fusion → state machine              WiFi reconnect, HTTP POSTs,     │
  OLED ───┘             │  buzzer · OLED · button · web server   device registration             │
  Flame DO ─ GPIO1      │  camera (OV3660) · sensor model                                       │
  Info button GPIO2     └───────────┬──────────────────────────────────────────┬────────────────┘
  Buzzer GPIO42                     │ Serial (UART0): CSV log for training     │ WiFi / HTTP
                                    ▼                                          ▼
                            PC: collect_serial.py            Flask backend (SQLite)
                            → train_sensor.py                 ├─ risk_score_service (ingest, alerts)
                            → export_c.py → sensor_model.h    ├─ telegram / email
                              (compiled into firmware)        ├─ yolo + hazard service (snapshots)
                                                              ├─ dispatch_service (SIMULATED fire dept)
                                                              └─ REST API ──► React dashboard
```

**Division of labour**

| Layer | Responsibility |
|---|---|
| ESP32 | Sense, decide the alarm state locally (works with no WiFi), sound the buzzer, show status on the OLED, send data and photos. |
| Backend | Store history, send Telegram/Email, analyse photos (YOLO + hazard logic), run the simulated dispatch countdown, serve the dashboard. |
| PC (ML kit) | Train models offline. Models are then shipped to the device (sensor model → flash header, CNN → SD card) or to the backend (YOLO weights). |

---

## 3. Hardware and wiring (updated)

### 3.1 What changed from the earlier diagram
* **Removed:** green / yellow / red status LEDs (GPIO 47 / 41 / 14) and the diffuse/acknowledge button (GPIO 19).
* **Kept:** info button, buzzer, OLED, INA219, everything else.
* **Consequence:** there is no separate "diffuse" button. The info button now does two jobs — a short press cycles OLED screens, a long press (1.5 s) silences the buzzer **and** acknowledges (cancels the dispatch countdown).
* Pins 14, 19, 41 and 47 are now free.

### 3.2 Modules and what each is for

| Module | Purpose in the project |
|---|---|
| Freenove ESP32-S3-WROOM CAM (N16R8, OV3660) | The single board: WiFi, camera, 8 MB PSRAM, 16 MB flash. |
| BME280 | Temperature, humidity, pressure — temperature rise is a fire signal; humidity/pressure give context. |
| ADS1115 | 16-bit I2C ADC. **Mandatory**: the camera uses most ADC1 pins and ADC2 is unusable with WiFi. Reads 3 MQ sensors + UV. |
| MQ-2 | Smoke / combustible gases (broad spectrum). |
| MQ-7 | Carbon monoxide (incomplete combustion). |
| MQ-135 | Air quality / VOC / smoke (broad spectrum). |
| GUVA-S12D | UV light — flame emits UV. |
| B35 IR flame sensor | Digital flame detect (LM393 comparator, DO output). |
| INA219 | Current / voltage / power monitor on the power path. |
| SSD1306 OLED 128×64 | Local status screens. |
| Buzzer | Local audible alert, a distinct pattern per state. |
| Info button | Short press: next screen. Long press: silence/acknowledge. |
| 3.7 V LiPo + TP4056 + boost converter (MT3608 / XL6009) | Battery power: charge/protect, then step up to 5 V. |
| Slide switch | Hard power cut, no microcontroller involved. |

### 3.3 GPIO allocation

| GPIO | Use | Notes |
|---|---|---|
| 1 | B35 flame sensor DO | `INPUT`; active LOW (`FLAME_ACTIVE_LOW`) — verify on your module |
| 2 | Info button | `INPUT_PULLUP`, other leg to GND, no resistor |
| 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18 | Camera (ribbon) | fixed by the board |
| 20 | I2C SDA | **also the native-USB D+ pin** — see cautions |
| 21 | I2C SCL | |
| 38, 39, 40 | SD_MMC (CMD / CLK / D0) | reserved for Phase 2, not wired |
| 42 | Buzzer | PWM tones via LEDC |
| 43, 44 | UART0 Serial via the bridge chip | used for logs and the training CSV |
| 48 | Onboard WS2812 | unused |
| **14, 19, 41, 47** | **FREE** | were red LED, diffuse button, yellow LED, green LED |
| 26–37 | Reserved by the module | octal PSRAM / flash — never use |
| 0, 3, 45, 46 | Strapping pins | deliberately avoided |

### 3.4 Power chain and rails

**As built now**
```
LiPo 3.7V ──► TP4056 (charge + protect) ──► slide switch ──► boost converter (set to 5.0 V)
                                                                    │ OUT+
                                                                    ▼
                                                  INA219 VIN+ ──► VIN- ──► 5V rail
```
| Rail | Feeds |
|---|---|
| 5 V | MQ-2, MQ-7, MQ-135 heater/VCC only; (ESP32 5V/VIN pin when running on battery) |
| 3.3 V (from the ESP32 3V3 pin) | ADS1115, BME280, INA219 logic, OLED, UV sensor, flame sensor, button pull-up logic |
| GND | Everything, common ground — jumper both breadboard GND rails together |

* **I2C is kept on 3.3 V.** MQ sensors are the only 5 V parts; their output goes through a divider before it reaches the ADS1115.
* The INA219 sits **in series** on the positive line (current flows through it); VIN+/VIN− are the two ends of the measured path, not "power in / ground".

**Optional later: INA219 on the battery side** (gives battery % — see §3.8)

### 3.5 Connection tables

**ADS1115 (0x48)**

| Pin | Connects to |
|---|---|
| VDD | 3.3 V |
| GND | GND |
| SCL / SDA | GPIO21 / GPIO20 |
| A0 | MQ-2 divider node |
| A1 | MQ-7 divider node |
| A2 | MQ-135 divider node |
| A3 | UV sensor AOUT (direct) |
| ADDR | unconnected (→ 0x48) |

**MQ-2 / MQ-7 / MQ-135** (identical pattern)

| Pin | Connects to |
|---|---|
| VCC | 5 V rail |
| GND | GND |
| AOUT | → 10 kΩ → **node** → 10 kΩ → GND; ADS1115 input is taken from the node |

The divider halves the up-to-5 V output to ≤ 2.5 V (safe for an ADS1115 powered at 3.3 V). Three dividers, six resistors. Firmware multiplies by `MQ_DIVIDER_RATIO = 2.0` when it needs the real AOUT voltage.

**GUVA-S12D (UV)**: VCC 3.3 V, GND, AOUT → ADS1115 A3 directly (low-voltage output).

**B35 flame sensor**: VCC **3.3 V** (so DO is a safe 3.3 V logic level), GND, DO → GPIO1.

**BME280 (0x76)**: VCC 3.3 V, GND, SCL → GPIO21, SDA → GPIO20.

**INA219 (0x40)**

| Pin | Connects to |
|---|---|
| VCC | 3.3 V |
| GND | GND |
| SCL / SDA | GPIO21 / GPIO20 |
| VIN+ | boost converter output (+) |
| VIN− | continues to the 5 V rail |

**SSD1306 OLED (0x3C)**: VCC 3.3 V, GND, SCL → GPIO21, SDA → GPIO20.

**Buzzer**: signal → GPIO42, GND → GND (3-pin module also VCC → 3.3 V). A bare passive piezo goes directly across GPIO42 and GND. Set `BUZZER_PASSIVE` in `config.h`: 1 = passive (tones), 0 = active (on/off only).

**Info button**: one leg → GPIO2, other leg → GND. Firmware enables the internal pull-up.

Four I2C devices share GPIO20/21 with different addresses (0x3C, 0x40, 0x48, 0x76) — no conflicts.

### 3.6 Breadboard zone plan
* **Left third:** ADS1115, BME280, INA219, OLED (all on the I2C bus — keep bus wires short).
* **Middle third:** MQ-2, MQ-7, MQ-135 and their six divider resistors (heaviest current — near the 5 V rail entry).
* **Right third:** UV sensor, flame sensor, buzzer, info button.
* TP4056, switch and boost converter are pre-assembled modules and sit off the breadboard, joined by two wires (5 V+ and GND) into the rail.

### 3.7 Wiring cautions (worth knowing for the viva)
1. **GPIO20 is the USB D+ pin.** It works as I2C SDA because USB CDC On Boot is disabled and you flash/monitor through the **UART** USB port. Do not plug the native USB port in at the same time. If the bus ever turns flaky, GPIO47/14 are now free to move I2C to. (Earlier notes said 19/20 must not be used for I2C while native USB is active — still true; that is why the native port must stay unused.)
2. **MQ-7 is on constant 5 V.** The datasheet calls for heater cycling (≈5 V / 1.4 V); without it CO sensitivity is reduced. The model is trained on whatever the sensor does at constant 5 V, so it is consistent, but note it as a limitation.
3. **MQ heaters draw roughly 450 mA combined at 5 V** (typical datasheet values), so battery runtime is hours, not days. The INA219 will show the real figure.
4. **TP4056 has no power-path.** Running the load while charging can confuse charge termination.
5. **Flame module at 3.3 V:** most LM393 breakouts work, but confirm it detects reliably.
6. **Buzzer current:** a bare piezo or transistor-driven module is fine from a GPIO; a bare electromagnetic buzzer needs a transistor.

### 3.8 Optional: moving the INA219 in front of the booster
Why: after the boost converter the INA219 only sees a regulated 5 V, so **battery % is impossible**. Before the booster its bus voltage *is* the battery voltage.

```
Now : switch → boost IN → boost OUT+ → INA219 VIN+ → VIN- → 5V rail
New : TP4056 OUT+ → switch → INA219 VIN+ → INA219 VIN- → boost IN+      and   boost OUT+ → 5V rail directly
```
1. Power off, battery disconnected.
2. Remove the INA219 from the boost-output line; connect boost OUT+ straight to the 5 V rail.
3. Switch output → INA219 VIN+.
4. INA219 VIN− → boost IN+.
5. Grounds, 3.3 V and SDA/SCL unchanged.
6. In `config.h` set `POWER_SENSE_ON_BATTERY_SIDE 1`.
7. Multimeter check before connecting the ESP32: boost output still 5.0 V.

Afterwards the INA219 reports *battery* current (≈1.5× the 5 V-side current), and the OLED shows battery voltage and %. Until you move it, the OLED shows 5 V-rail volts/current and "Battery %: n/a".

---

## 4. Firmware (v2.2) — how it works

### 4.1 Arduino IDE settings (confirmed during bring-up)
ESP32S3 Dev Module · PSRAM: **OPI PSRAM** · Flash Mode: **DIO 80 MHz** (QIO hung on large binaries) · USB CDC On Boot: **Disabled** (enabled caused hangs) · Partition: **Huge APP** · Flash 16 MB. Flash and monitor through the **UART** USB port.

Libraries: Adafruit BME280 (+ Unified Sensor), Adafruit ADS1X15, Adafruit SSD1306 (+ GFX), ArduinoJson **v7** (6.x does not compile). TFLite Micro ships with the core. Copy `secrets.h.example` → `secrets.h` and fill in WiFi credentials.

### 4.2 Two execution contexts
* **`loop()` on core 1** — everything local and time-critical. It never waits on the network.
* **Network task on core 0** — owns WiFi and all HTTP. `loop()` pushes small jobs into a queue (`NET_QUEUE_LENGTH 8`); the task sends them. If WiFi or the backend dies, sensors, state machine, buzzer and OLED keep running; failed uploads are dropped (SD buffering is Phase 2). After 3 consecutive failures the task backs off for 5 s.

### 4.3 One pass of `loop()`
Every pass (fast): handle web requests → poll the flame pin (every 100 ms) → read the INA219 (1 Hz) → handle the button → tick the buzzer → tick the OLED.

Once per second (`SENSOR_SAMPLE_INTERVAL_MS`):
1. `sensors_read()` — BME280 + ADS1115 (4 channels, ≈40 ms), checks the devices still answer on I2C.
2. Push the sample into the 30-sample window (or reset the window if the read was invalid).
3. `window_compute()` — mean, standard deviation, slope per channel.
4. Run the sensor model (if one is compiled in and everything is ready) → advisory result.
5. `fusion_compute()` — 0–100 risk score.
6. (Optional, off by default) let the sensor model *raise* the score.
7. `state_machine_update()` — new state, whether to take a snapshot.
8. If the state is NORMAL → feed the baseline.
9. Buzzer state update; print the training CSV line; queue snapshot + sensor upload as needed.

**Fixed 1 Hz is deliberate.** Window features (slope, std) mean the same thing in training and on the device only if the sample rate never changes; the *state* only changes the *upload* cadence.

### 4.4 Sensors and the baseline (`sensors.cpp`)
* **Flame debounce:** the pin is polled every 100 ms into a 10-slot history; the flame is "detected" when ≥ 4 of the last 10 polls were active (~40 % duty over ~1 s). A flickering real flame counts, a single glitch does not.
* **Raw ADS counts** (0.125 mV/count at GAIN_ONE ±4.096 V) are used everywhere. The `*_ppm` values in the payload are **placeholder** linear estimates kept for the dashboard; train on raw counts.
* **Runtime fault handling:** each cycle pings the BME280 and ADS1115; a lost device is flagged, retried every 10 s, and recovers without a reboot. A failed group does not poison the other group's baseline.
* **Baseline calibration (stage 1 of the sensor plan — not ML):**
  * Temperature baseline is learned fresh each boot (room temperature changes by day).
  * Gas/UV baseline waits for the MQ heaters to warm up (`MQ_HEATER_WARMUP_MS` = 3 min), then needs 60 quiet samples → "ready" ≈ 4 min after power-up.
  * Learning only happens while the state is NORMAL.
  * **Self-protection against slow fires being "learned as normal":** learning freezes whenever any MQ is > 25 % above baseline or temperature is > 1 °C away; the baseline is clamped to 0.5–1.6× (gas) / ±10 °C (temp) of its first value; the EMA is slow (~5 min).
  * The gas/UV baseline is saved to flash (NVS) every 30 min and restored at boot. Hold the info button 3 s at power-up to wipe it.

### 4.5 Window features (`window.cpp`)
A ring buffer of the last 30 valid samples (30 s). Channels: temp, MQ-2, MQ-7, MQ-135, UV, flame. For each: mean, population std, least-squares slope per second. Any invalid read resets the buffer (a gap breaks the fixed-rate assumption). These feed the rate-of-rise term in fusion, the sensor model, and the backend (`window_json`).

### 4.6 Fusion score (`fusion.cpp`) — 0 to 100, rule-based and transparent

| Component | Max points | How it is earned |
|---|---|---|
| Flame | 35 | debounced flame detected |
| Temperature | 25 | best of: deviation from baseline (+5 °C = full) · rate of rise (+6 °C/min = full) · absolute level (≥ 45 °C = 40 %, ≥ 57 °C = full) |
| Gas | 30 | worst MQ deviation vs baseline (+150 % = full) — only after heater warm-up and baseline ready |
| Multi-gas agreement | 10 | ≥ 2 MQ sensors above +40 % |
| UV | 10 | UV above its baseline (~0.3 V = full) |

Totals clamp to 100. **Without flame the maximum is 75**, so a smoldering fire can reach CONFIRMING and FIRE. Special rules: a reading ≥ 57 °C floors the score at CONFIRMING regardless of baseline (fixed-temperature heat-detector behaviour); before warm-up, a coarse absolute MQ fallback adds 10 points.

Thresholds: **PRECURSOR 30 · CONFIRMING 50 · FIRE 65.** (Placeholders — to be revisited once the trained model and real trial data exist.)

### 4.7 State machine (`state_machine.cpp`)

```
NORMAL ──(flame or score ≥ 30)──► PRECURSOR ──(flame or score ≥ 50)──► CONFIRMING ──(see below)──► FIRE_CONFIRMED
   ▲                                  │ score < 30 for 15 s                │ evidence lost             │ held ≥ 30 s and
   └──────────────────────────────────┘◄───────────────────────────────────┘                           │ no evidence → back to CONFIRMING
```
* **CONFIRMING → FIRE_CONFIRMED** needs the evidence to persist for **8 s** and be *fire-level*: score ≥ 65 on its own, **or** flame **plus** corroboration (score ≥ 50). A flame signal alone (sunlight, a lamp) holds at CONFIRMING (Telegram + Email) but never escalates by itself.
* Transient triggers (a lighter flick) die out: the 8 s window and the 15 s cooldown reject them.
* A snapshot is requested on entering PRECURSOR, CONFIRMING and FIRE_CONFIRMED.

### 4.8 Buzzer, button, OLED
**Buzzer patterns** (non-blocking, on GPIO42)

| State | Pattern |
|---|---|
| NORMAL | silent |
| PRECURSOR | one short beep every 6 s |
| CONFIRMING | double beep every 1.5 s |
| FIRE_CONFIRMED | continuous tone |

Silencing affects the **buzzer only** (never the state or the backend alerts). It re-arms automatically when severity increases or the state returns to NORMAL, and the silence lasts 5 min (60 s during FIRE_CONFIRMED, then it sounds again).

**Info button (GPIO2, debounced 30 ms)**

| Action | Effect |
|---|---|
| Short press | next OLED screen (also wakes it) |
| Long press (1.5 s) while elevated | silence buzzer **and** `ack_seq` +1 → backend cancels the dispatch countdown; OLED shows "ACK SENT" |
| Hold 3 s at power-up | wipe the saved gas baseline |

**OLED screens** — STATUS (state, risk bar, WiFi/server OK, flame, hint) · SENSORS (T/H/P, MQ-2/7/135 raw, UV, flame) · POWER (battery or 5 V rail, current, power) · NETWORK (IP, RSSI, backend OK, uptime). Sleeps after 30 s in NORMAL; any elevated state wakes it and pins it to STATUS.

### 4.9 Camera
OV3660, JPEG, SVGA with PSRAM (QVGA fallback), 2 frame buffers, grab-latest. The camera clock uses LEDC timer 3 / channel 7 so the buzzer (channel 0) can change pitch without disturbing it. A mutex shares the camera between the web handler and the network task. Evidence snapshots discard one stale frame first.

### 4.10 Local web server (port 80)
* `GET /capture` — JPEG on demand (used by the dashboard's camera panel via the backend proxy). Stores a copy in the backend at most once per 10 s so a 1 fps Live View does not flood the gallery; `?store=0` disables storing.
* `GET /status` — JSON: device id, camera online, WiFi, state, buzzer silenced, battery %, uptime.

### 4.11 Registration
At boot the device derives its id (`fs-<MAC>`), and as soon as WiFi connects (and every 60 s) it POSTs its id, IP and port to the backend. IP or room changes never need a reflash. The dashboard assigns rooms and can pin a manual IP override.

### 4.12 Payload sent to `POST /api/sensor-data`
```json
{
  "device_id": "fs-AABBCCDDEEFF", "timestamp_ms": 123456,
  "state": "PRECURSOR", "risk_score": 41,
  "buzzer_silenced": false, "ack_seq": 0, "sensor_fault": false,
  "sensors": { "temperature_c": 27.4, "humidity_pct": 48, "pressure_hpa": 1008,
               "mq2_ppm": 120, "mq7_ppm": 20, "mq135_ppm": 30, "uv_index": 0.2,      // placeholder estimates
               "mq2_raw": 12000, "mq7_raw": 5000, "mq135_raw": 6000, "uv_raw": 40,   // use these for ML
               "flame_detected": false, "reading_valid": true },
  "fusion":  { "temp_deviation": 1.2, "temp_rate_c_per_min": 2.5, "gas_deviation_pct": 80,
               "gas_agree_count": 2, "gas_terms_active": true },
  "power":   { "valid": true, "sense_on_battery": false, "bus_v": 5.0, "current_ma": 450,
               "power_mw": 2250, "battery_v": 0, "battery_pct": -1, "battery_low": false },
  "window":  { "temp": {"mean": 27.3, "std": 0.1, "slope_per_s": 0.01}, "mq2": {...}, ... },   // when ready
  "ml":      { "class": "NORMAL", "conf": 0.93, "anomaly": 0.41, "anomalous": false, "version": "..." }   // when a model is installed
}
```
Cadence: every 30 s as a heartbeat in NORMAL; every 1 s while elevated; immediately on a state change. New fields are optional, so older firmware still works with the patched backend.

### 4.13 Key tunables (`config.h`)

| Setting | Default | Meaning |
|---|---|---|
| `SENSOR_SAMPLE_INTERVAL_MS` | 1000 | the one fixed sample rate |
| `WINDOW_SIZE` | 30 | samples per feature window |
| `FLAME_MIN_HITS` / `FLAME_HISTORY` | 4 / 10 | flame debounce |
| `MQ_HEATER_WARMUP_MS` | 180000 | gas terms ignored until then |
| `BASELINE_*` | see file | warm-up samples, EMA length, freeze gates, anchor clamps, NVS save interval |
| `RISK_THRESHOLD_*` | 30 / 50 / 65 | PRECURSOR / CONFIRMING / FIRE |
| `SUSTAINED_CONFIRM_WINDOW_MS` | 8000 | evidence must persist this long |
| `PRECURSOR_COOLDOWN_MS` / `FIRE_HOLD_MS` | 15000 / 30000 | de-escalation timing |
| `HEARTBEAT_INTERVAL_MS` / `UPLOAD_INTERVAL_ELEVATED_MS` | 30000 / 1000 | upload cadence |
| `BUZZER_PASSIVE` | 1 | 1 passive piezo, 0 active module |
| `BUZZER_SILENCE_MS` / `_FIRE_MS` | 300000 / 60000 | silence durations |
| `POWER_SENSE_ON_BATTERY_SIDE` | 0 | 1 after moving the INA219 |
| `SERIAL_CSV_LOG` | 1 | print the training CSV line each second |
| `SENSOR_ML_AFFECTS_SCORE` | 0 | 0 = model advisory only; 1 = it may raise (never lower) the score |
| `I2C_CLOCK_HZ` | 100000 | raise to 400000 only if the bus is clean |

---

## 5. Firmware — purpose of every file

Folder `esp32s3_cam_main/` (all files must sit together next to the `.ino`).

| File | Purpose |
|---|---|
| `esp32s3_cam_main.ino` | Entry point: `setup()` boots every module; `loop()` runs the 1 Hz cycle and all fast ticks; local web server handlers; training CSV line. |
| `config.h` | **Every pin, address, threshold and timing constant** in one place; includes `secrets.h`. |
| `secrets.h.example` | Template for `secrets.h` (WiFi name/password — keep out of git). |
| `sensors.h / .cpp` | BME280 + ADS1115 reads, flame debounce, runtime I2C fault detection, baseline calibration (with freeze, anchor clamp, NVS persistence). |
| `window.h / .cpp` | 30-sample ring buffer and window statistics (mean/std/slope). |
| `fusion.h / .cpp` | Rule-based 0–100 risk score. |
| `state_machine.h / .cpp` | The four-state alarm logic and snapshot triggers. |
| `sensor_ml.h / .cpp` | On-device sensor model: builds the 16 baseline-relative features and runs the RandomForest (class) + IsolationForest (anomaly). |
| `sensor_model.h` | **Stub** until you train; replaced by the generated header from `export_c.py` (trees as const arrays in flash). |
| `buzzer.h / .cpp` | Non-blocking alert patterns, silence/re-arm rules, LEDC handling (core 2.x and 3.x). |
| `buttons.h / .cpp` | Debounced info button: short press, long press, boot-hold. |
| `display.h / .cpp` | SSD1306 screens, sleep/wake, runtime I2C recovery. |
| `vision.h / .cpp` | Mounts the microSD, loads the two `.tflite` models into PSRAM, runs CNN + YOLO on every snapshot (own task), attaches the results to the upload. |
| `camera.h / .cpp` | Camera init, mutex-protected capture/return, stale-frame flush. |
| `network_client.h / .cpp` | The network task and job queue: WiFi reconnect, sensor and snapshot uploads, timeouts, backoff. |
| `device_register.h / .cpp` | Device id from the MAC; periodic self-registration with the backend. |
| `i2c_util.h` | `i2c_ping()` helper used to detect a lost I2C device. |

Test assets shipped with the firmware zip (`tests/`): host-side tests for fusion, state machine, baseline, window, flame debounce, buzzer and button logic (`run_tests.sh`, needs only g++).

---

## 6. Backend (Flask + SQLite)

### 6.1 Request flow for a sensor reading
```
ESP32 ──POST /api/sensor-data──► routes/sensor_routes.py
         └► services/risk_score_service.process_sensor_reading():
              1. create a bare devices row if the device is unknown yet
              2. compute gas-source hint (gas_pattern_service)
              3. INSERT sensor_readings (incl. raw counts, power, window, ml, ack_seq)
              4. update the device's last_state / last_seen / room
              5. state changed? → events row + alerts (Telegram / Email, with the newest snapshot)
              6. dispatch_service.on_reading() → simulated fire-department countdown
```
Alerts fire **once per state change**, not on every upload, so the 1-second elevated upload rate does not spam you.

### 6.2 Alert policy (`config.ALERT_POLICY`)

| State | Telegram | Email | Severity |
|---|---|---|---|
| NORMAL | – | – | – |
| PRECURSOR | yes | – | info |
| CONFIRMING | yes | yes | warning |
| FIRE_CONFIRMED | yes | yes | critical |

### 6.3 Simulated fire-department dispatch (`services/dispatch_service.py`)
* FIRE_CONFIRMED → owner gets a Telegram message and a **30 s countdown** starts.
* **Cancel** by holding the info button (firmware `ack_seq` increases) or `POST /api/dispatch/cancel`.
* No cancel → a message marked **[SIMULATION — no real call was placed]** (room, device, risk, camera classification/hazard, evidence link, photo) goes to the "Fire Dept (SIM)" chat (`TELEGRAM_FIRE_DEPT_SIM_CHAT_ID`) or the normal chat.
* Still FIRE_CONFIRMED 2 min after a cancel → the countdown restarts. State falling back to NORMAL/PRECURSOR during the countdown clears it automatically. A background timer fires a due countdown even if the device went offline mid-fire.
* Every step is logged to `dispatch_events` and to the Detection Timeline (event type `ALERT_SENT`, so the dashboard needs no change to show it).
* It **never** dials a real number: an unverified automated emergency call is a liability and a false-alarm risk. A real deployment would ring a pre-configured contact (Twilio, planned) or use a certified monitoring partner.

### 6.4 Snapshot → hazard pipeline
`POST /api/camera/snapshot` (always saved) → `ml_inference_service.classify_snapshot` (CNN; **currently the stub**) → `yolo_service.detect_flames` (flame boxes, optional) → `hazard_service.assess` → level **HAZARDOUS / CONTROLLED / NONE / UNKNOWN**. Escalation is one-way: any single hazardous signal wins (CNN says hazardous, flame area ≥ 15 % of frame, or area grew ≥ 1.5× within 3 min). "Detector found nothing" is never treated as proof of no fire (its box recall is ~57 %).

### 6.5 REST API

| Route | Purpose |
|---|---|
| `POST /api/sensor-data` · `GET /api/sensor-data/latest` · `GET /api/sensor-data/history` | ingest; live gauge tiles; trend charts |
| `POST /api/device/register` · `GET /api/devices` · `GET /api/devices/<id>` · `PUT /api/devices/<id>/room` · `PUT /api/devices/<id>/override` | self-registration, device list, room assignment, manual IP pin |
| `POST /api/camera/snapshot` · `GET /api/camera/capture-proxy` · `GET /api/camera/snapshots` · `GET /api/camera/snapshots/<id>/file` | snapshot upload; live view through the backend; gallery; image file |
| `GET /api/events` · `GET /api/events/recent` | Detection Timeline |
| `GET /api/alerts/history` · `POST /api/alerts/test` | alert log; send a test alert |
| `GET/POST /api/rooms` · `DELETE /api/rooms/<id>` · `GET/POST /api/rooms/<id>/appliances` · `DELETE /api/appliances/<id>` · `GET/POST/DELETE /api/contacts` | room profiles, appliances, emergency contacts |
| `GET /api/model-info` | CNN manifest for the AI/ML page |
| `GET /api/dispatch/status?device_id=` · `POST /api/dispatch/cancel` · `GET /api/dispatch/events` | **new**: simulated dispatch |

### 6.6 Database tables (`database/schema.sql`; migrates itself on start-up)

| Table | Holds |
|---|---|
| `rooms`, `appliances`, `emergency_contacts` | profiles used by the dashboard |
| `devices` | id, name, room, IP/port, manual override, RSSI, last state/seen |
| `sensor_readings` | every reading: state, risk, T/H/P, ppm estimates, **raw counts**, deviations, gas hint, power, ack_seq, buzzer_silenced, sensor_fault, `window_json`, `ml_json` |
| `events` | Detection Timeline (state changes, snapshots, alerts) |
| `snapshots` | image path, reason, CNN class/confidence, YOLO status/boxes/area/growth, hazard level + reasons |
| `alerts` | every Telegram/Email attempt with success/error |
| `dispatch_events` | **new**: countdown started / cancelled / auto-cleared / re-armed / dispatched (simulated) |

### 6.7 Backend files

| File | Purpose |
|---|---|
| `run.py`, `app.py` | Start-up; `create_app()` registers blueprints and starts the dispatch timer. |
| `config.py` | All settings from `.env`: Telegram, email, paths, YOLO and hazard thresholds, alert policy, dispatch options. |
| `env.example` | Template for `.env` (token, chat id, SIM chat id, SMTP, dispatch options). |
| `db.py` | SQLite connection, schema creation, column migrations. |
| `database/schema.sql` | All tables. |
| `routes/sensor_routes.py` | Sensor ingest and history. |
| `routes/device_routes.py` | Registration, device list, room assignment, IP override. |
| `routes/camera_routes.py` | Snapshot upload, live proxy, gallery, file serving. |
| `routes/events_routes.py` | Timeline queries. |
| `routes/alerts_routes.py` | Alert history and test alert. |
| `routes/profile_routes.py` | Rooms, appliances, emergency contacts. |
| `routes/model_routes.py` | Model manifest for the AI/ML page. |
| `routes/dispatch_routes.py` | **new** — dispatch status / cancel / events. |
| `services/risk_score_service.py` | The ingest brain: store, state-change events, alert dispatch, dispatch hook. |
| `services/telegram_service.py` | Telegram Bot API (text + photo, optional alternate chat). |
| `services/email_service.py` | Gmail SMTP with optional snapshot attachment (needs an App Password). |
| `services/gas_pattern_service.py` | Interim rule-based "which MQ is most elevated" hint (honest: MQ sensors are not gas-specific). |
| `services/yolo_service.py` | Runs the YOLO11n flame detector (optional, never raises). |
| `services/hazard_service.py` | Combines CNN + YOLO + growth into a hazard level. |
| `services/ml_inference_service.py` | CNN snapshot classifier — **stub in the sent zip**; your kit's `ml_inference_sevice.py` is the real one (copy it here with the correct spelling). |
| `services/dispatch_service.py` | **new** — simulated fire-department dispatch. |
| `tests/test_hazard_pipeline.py` | 9 tests for the YOLO/hazard logic. |
| `tests/test_dispatch_service.py`, `tests/test_sensor_ingest.py` | **new** — 11 + 9 tests. |
| `requirements.txt`, `Backend_README.md`, `README_BACKEND_YOLO.md` | dependencies and setup notes. |
| `models/fire_yolo.pt` (you add) | YOLO weights. CNN path via `FIRE_MODEL_PATH`. |

### 6.8 Environment variables (`.env`)
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_FIRE_DEPT_SIM_CHAT_ID` (optional), Gmail SMTP settings + recipient, `FIRE_YOLO_PATH`, `FIRE_MODEL_PATH`, `YOLO_CONF`, `HAZARD_*`, `DISPATCH_ENABLED`, `DISPATCH_COUNTDOWN_S`, `DISPATCH_REARM_AFTER_CANCEL_S`, `DISPATCH_RESET_AFTER_NORMAL_S`, `DASHBOARD_URL`, `PUBLIC_BACKEND_URL` (use your LAN IP so snapshot links open on a phone). Keep `.env`, the database and `venv/` out of zips and git.

---

## 7. ML — CNN, YOLO, sensor model

Everything is run in **PowerShell from the `fire_sentinel_ml_kit` folder**. The CNN and YOLO scripts need `tf-keras` and `$env:TF_USE_LEGACY_KERAS = "1"` on your TensorFlow 2.21 / Python 3.12 install; the sensor scripts do not use TensorFlow.

### 7.1 Three models, three jobs

| Model | Input | Output | Runs on | Status |
|---|---|---|---|---|
| **CNN** MobileNetV2 α0.35, 96 px, INT8 | camera frame | NO_FIRE / CONTROLLED_FLAME / HAZARDOUS_FIRE | ESP32 (SD card) and/or backend | trained + quantized; not yet on the board |
| **YOLO11n** (single class "fire") | camera frame | flame boxes → size and growth | backend | trained; secondary signal |
| **Sensor model** RF + IsolationForest | 30 s window of baseline-relative sensor features | class + "not normal" flag | ESP32 (compiled into flash) | kit ready; needs real data |

### 7.2 Sensor model — the three stages
1. **Baseline calibration (not ML)** — on the device (`sensors.cpp`). Every logged row carries the baseline that was active, so features are *relative* and transfer across rooms, sensor units and days.
2. **Classifier** — RandomForest (40 trees, depth ≤ 8) on 16 window features → NORMAL / CONTROLLED_FLAME / HAZARDOUS_FIRE.
3. **Anomaly detector** — IsolationForest trained on **NORMAL windows only**; flags "this is not normal" even for fires never recorded. Threshold = 99th percentile of normal training scores.

The 16 features: temperature (deviation, std, slope/min), and for each of MQ-2, MQ-7, MQ-135 (relative mean, relative std, relative slope/min), UV (deviation, std, slope — normalized), flame duty.

**Where things live**

| What | Path |
|---|---|
| Recorded sessions | `ml/sensor/dataset/raw/<LABEL>__<scenario>__<time>.csv` |
| Models, manifest, report, plots | `ml/sensor/artifacts/` |
| Firmware model header | `ml/sensor/firmware_src/sensor_model.h` → copied into the sketch folder → compiled into flash (**no SD card**) |
| Synthetic demo data (pipeline test only) | `ml/sensor/dataset/demo_synthetic/` |

**Workflow**
```powershell
python tools/collect_serial.py --list-ports
python tools/collect_serial.py --port COM5 --label NORMAL --scenario bedroom_evening --minutes 10
python ml/sensor/train_sensor.py          # leave-one-session-out evaluation → artifacts/sensor_report.md
python ml/sensor/export_c.py --firmware-dir "C:\path\to\esp32s3_cam_main"
```
Record ≥ 6 sessions per class over different days/places (NORMAL incl. everyday disturbances; CONTROLLED_FLAME = candle/lighter/stove; HAZARDOUS_FIRE = only a tiny supervised source such as one sheet of paper in a metal tray outdoors with water/extinguisher at hand — never real fires indoors). The evaluation holds out whole recordings, because neighbouring windows overlap 29/30 and a random split would leak.

**Using it on the device:** default is **advisory** (`SENSOR_ML_AFFECTS_SCORE 0`) — result goes to the backend and serial log, alarm logic unchanged. After validation on real data set it to 1; the model can then only *raise* the rule-based score.

### 7.3 ML kit — purpose of every file

| Path | Purpose |
|---|---|
| `ml/cnn/cnn_common.py` | shared constants/data pipeline for the CNN |
| `ml/cnn/train_cnn.py` | trains the MobileNetV2 classifier → `fire_cnn.keras` |
| `ml/cnn/quantize_int8.py` | post-training INT8 quantization → `fire_cnn_int8.tflite` (~612 KB) |
| `ml/cnn/evaluate.py`, `benchmark.py` | FP32 vs INT8 accuracy / recall / false-alarm; speed and size |
| `ml/cnn/dataset/raw`, `split`, `artifacts/` | sorted images, train/val/test split, model outputs + `model_manifest.json` |
| `ml/yolo/train_yolo.py` | YOLO11n training (run on Colab GPU) |
| `ml/yolo/yolo_sources.json`, `sources/`, `dataset/`, `artifacts/` | dataset recipe, original Roboflow sets, generated single-class dataset, `fire_yolo.pt` + plots |
| `tools/dataset_split.py` | builds the CNN train/val/test split |
| `tools/model_manifest_generator.py` | writes `model_manifest.json` |
| `tools/prepare_yolo_dataset.py`, `preview_boxes.py` | builds the YOLO dataset; visual check of boxes |
| `tools/collect_serial.py` | **new** — records labelled sensor sessions from the serial port |
| `tools/make_demo_data.py` | **new** — synthetic sessions to smoke-test the sensor pipeline (never real results) |
| `ml/sensor/sensor_common.py` | **new** — shared feature math (mirrors firmware `window.cpp` / `sensor_ml.cpp`) |
| `ml/sensor/train_sensor.py` | **new** — trains + evaluates RF and IsolationForest |
| `ml/sensor/export_c.py` | **new** — trees → `sensor_model.h` |
| `ml/sensor/firmware_src/` | **new** — `sensor_ml.h/.cpp` and the stub `sensor_model.h` (kit flattened on 29 Oct: it had been unpacked one level too deep, at `ml/sensor/ml/sensor/`) |
| `ml/sensor/tests/test_parity.py` | **new** — compiles the real firmware inference code and proves it matches scikit-learn |
| `backend_services/ml_inference_sevice.py` | your real CNN inference service (note the spelling — install it in `backend/services/` as `ml_inference_service.py`) |

Reference documents in the project: *Fire Sentinel — Complete ML Project Record* (Claude doc), `Fire_Sentinel_ML_All_Code.md`, `fire_sentinel_ml_full_source_FINAL.zip`, plus the two roadmap PDFs (*Prototype 2 Blueprint*, *Reimagined Dashboard Features and Workflow*).

---

## 8. Dashboard (React)
*(From the project notes — not re-reviewed in this session.)* React + Vite + Tailwind; custom SVG speedometer gauge (GaugeTile), live camera panel (Live View polls at 1 fps and stops after 60 s, pulsing LIVE badge), snapshot gallery (auto-polls every 5 s), detection timeline, device setup (rooms, IP override), room/appliance profile pages, AI/ML page. 27 files.

**To add:** a "Fire Dept (SIMULATED)" panel — countdown from `/api/dispatch/status`, a Cancel button → `POST /api/dispatch/cancel`, history from `/api/dispatch/events`. Dispatch events already appear on the timeline. Optionally show battery % and the sensor model's class/anomaly (`ml_json`) once those exist.

---

## 9. End-to-end walk-throughs

**A. Quiet night.** 1 Hz sampling, baseline slowly tracking, state NORMAL, buzzer silent, OLED asleep after 30 s, heartbeat to the backend every 30 s, registration every 60 s.

**B. Burnt toast (false alarm).** Gas rises + a little temperature → score ≥ 30 → PRECURSOR: one short beep every 6 s, a snapshot is taken, Telegram "PRECURSOR". Air clears; after 15 s below 30 it returns to NORMAL. Long-press silences the beep if it is annoying.

**C. Smoldering fire, no flame.** Gas climbs on all three MQ sensors (+ agreement bonus), temperature rises → score passes 50 → CONFIRMING (double beep, Telegram + Email with photo); score ≥ 65 sustained 8 s → FIRE_CONFIRMED (continuous tone). Backend starts the 30 s countdown message. If nobody cancels → simulated dispatch message goes to the "Fire Dept (SIM)" chat.

**D. Candle / lighter flick.** Flame flicker is debounced; 2 s of flame never reaches the 8 s window and decays back to NORMAL. A candle left burning: flame alone → PRECURSOR → CONFIRMING (alerts) but **not** FIRE_CONFIRMED unless gas/temperature corroborate.

**E. Someone is on site and it is under control.** During the countdown they hold the info button 1.5 s → buzzer silences, `ack_seq` increases, backend cancels ("cancelled by device button"). If it is still FIRE_CONFIRMED 2 min later the countdown restarts.

**F. WiFi or backend down.** Detection, buzzer, OLED and button keep working; uploads are dropped (not buffered); the network task retries WiFi every 10 s and backs off 5 s after repeated backend failures; registration is re-sent as soon as WiFi returns.

**G. A sensor wire comes loose.** The I2C ping flags the device, `sensor_fault` is raised (OLED shows FLT), the fusion ignores that group, and it recovers automatically when reconnected.

---

## 10. Testing and verification status

| What | How | Result |
|---|---|---|
| Fusion, state machine, baseline freeze/anchor, window slope, flame debounce | host-side C++ tests (PC) | 9 scenarios pass (smolder without flame, flame only, flame + gas, transient, 60 °C floor, slow creep…) |
| Buzzer silence/re-arm, button debounce/long-press | host-side C++ tests | 13 checks pass |
| Firmware sensor-model inference vs scikit-learn | `test_parity.py` compiles the real `sensor_ml.cpp` | 678 windows: class and anomaly-flag agreement 100 %, max probability difference 1e-4 |
| Firmware hardware-facing files | syntax-checked against stub libraries (real ArduinoJson v7) | clean |
| Backend | `python -m unittest discover -s tests` | 29 tests pass (9 existing + 11 + 9) |
| Serial collector | replayed fake firmware output | OK |
| **Not done** | real ESP32 core compile, flashing, camera + buzzer together, OLED timing, WiFi-loss behaviour, real data training, CNN on the board | — |

First things to check on the real board: it compiles; the camera still captures while the buzzer sounds; unplugging the router leaves the buzzer/OLED/state machine running; a test FIRE_CONFIRMED reading to the backend produces the countdown and the Telegram message.

---

## 11. Known limitations and open items
1. **CNN is not on the board yet.** `.tflite` not copied to the SD card, no SD/TFLite inference code in the firmware (Phase 2), not tested on real OV3660 frames. Backend still has the stub classifier.
2. **No real sensor data yet** — the sensor model and all fusion thresholds are placeholders until sessions are recorded.
3. **Fusion weights/thresholds** (35/10/25/30/10; 30/50/65) are hand-set; compare them with the trained model's results.
4. **MQ sensors:** not gas-specific, drift with age/temperature/humidity; MQ-7 not heater-cycled; 24–48 h burn-in recommended.
5. **Battery %:** unavailable until the INA219 is moved to the battery side. Runtime is hours (heaters). TP4056 has no power-path.
6. **GPIO20 doubles as USB D+** — keep the native USB port unplugged.
7. **Failed uploads are dropped**, not buffered (SD logging is Phase 2).
8. **Dispatch is simulated** and the dashboard panel is not built. Twilio call escalation to a verified contact is planned.
9. **Cloud deployment:** the camera proxy needs the backend to reach the ESP32's LAN IP; it breaks if the backend is hosted in the cloud without a tunnel/port-forward.
10. **Hygiene:** WiFi credentials belong in `secrets.h` (never shared/committed — change the password that was in the earlier zip); keep `.env`, `*.db` and `venv/` out of zips; fill in `.env` (the copy sent had empty values).

---

## 12. Quick reference

**Sensor addresses:** OLED 0x3C · INA219 0x40 · ADS1115 0x48 · BME280 0x76.
**ADS channels:** A0 MQ-2 · A1 MQ-7 · A2 MQ-135 · A3 UV.
**Pins:** flame 1 · info button 2 · SDA 20 · SCL 21 · buzzer 42 · UART0 43/44 · SD (reserved) 38/39/40 · free 14/19/41/47.
**Timing:** sample 1 s · flame poll 100 ms · heartbeat 30 s · elevated upload 1 s · MQ warm-up 3 min · baseline ready ≈ 4 min · sustained window 8 s · PRECURSOR cooldown 15 s · FIRE hold 30 s · dispatch countdown 30 s.
**Thresholds:** PRECURSOR 30 · CONFIRMING 50 · FIRE 65 · absolute temperature floor 57 °C.
**Alerts:** PRECURSOR → Telegram · CONFIRMING / FIRE_CONFIRMED → Telegram + Email · FIRE_CONFIRMED → + simulated dispatch countdown.
**Button:** short = next screen · long (1.5 s) = silence + acknowledge · hold 3 s at boot = wipe saved baseline.
**Backend start:** `python run.py` · tests: `python -m unittest discover -s tests`.
**Sensor ML:** `collect_serial.py` → `train_sensor.py` → `export_c.py` → copy `sensor_model.h` → flash.
**Arduino settings:** ESP32S3 Dev Module · OPI PSRAM · DIO 80 MHz · CDC On Boot Disabled · Huge APP · UART USB port.
