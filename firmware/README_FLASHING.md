# Flashing Fire Sentinel (firmware v2.3) with the Arduino IDE

Board: Freenove ESP32-S3-WROOM CAM (N16R8: 16 MB flash, 8 MB OPI PSRAM, OV3660).
Verified to compile with **esp32 core 3.3.12** (46 % of the Huge APP partition).

## 1. One-time setup
1. **Board package:** Tools → Board → Boards Manager → install **esp32 by Espressif Systems** (3.x; 3.3.12 tested).
2. **Libraries** (Sketch → Include Library → Manage Libraries):
   | Library | Version |
   |---|---|
   | Adafruit BME280 Library (+ Adafruit Unified Sensor) | latest |
   | Adafruit ADS1X15 | latest |
   | Adafruit SSD1306 (+ Adafruit GFX, Adafruit BusIO) | latest |
   | **ArduinoJson** | **7.x** — your installed 6.21.6 does **not** compile; click *Update* |

   Nothing to install for the AI models: TensorFlow Lite Micro and the JPEG decoder ship with the esp32 core.
   Adafruit INA219 is no longer used.
3. **WiFi:** `esp32s3_cam_main/secrets.h` holds `WIFI_SSID` / `WIFI_PASSWORD` (template: `secrets.h.example`).
4. **Backend address:** `config.h` → `BACKEND_HOST "10.111.193.119"`. This must be the LAN IP of the PC running `python run.py`, on the same WiFi.

## Final pin map (as wired; checked against Fire_Sentinel_Wiring_Diagram.pdf)
| GPIO | Part | config.h |
|---|---|---|
| 1 | IR flame module DO (active LOW) | `FLAME_DIGITAL_GPIO 1`, `FLAME_ACTIVE_LOW true` |
| 2 | Info button (other side to GND, internal pull-up) | `INFO_BUTTON_GPIO 2` |
| 20 / 21 | I2C SDA / SCL: BME280 (0x76/0x77), ADS1115 (0x48) and SSD1306 OLED (0x3C), shared bus | `I2C_SDA_GPIO 20`, `I2C_SCL_GPIO 21` |
| 42 | Buzzer | `BUZZER_GPIO 42` (`BUZZER_PASSIVE 1`; set 0 for an active buzzer) |
| 38 / 39 / 40 | Onboard microSD slot (internal traces, no wiring) | `SD_MMC_*_GPIO` |
| 4–13, 15–18 | Camera ribbon (fixed) | — |
| ADS A0 / A1 / A2 / A3 | MQ-2 / MQ-7 / MQ-135 (each through a 10k/10k divider) / UV AOUT direct | `ADS_CH_*`, `MQ_DIVIDER_RATIO 2.0` |

- Removed and free: LEDs (GPIO 14/41/47), second button (GPIO 19), INA219, battery chain.
- **BME280:** fitted, so `BME280_FITTED 1` (tries I2C 0x76, then 0x77). Without one, set it to 0: temperature, humidity and pressure then read as 0 and fusion uses flame, gas and UV only.
- **Different divider resistors:** if your MQ dividers aren't 10k/10k, set `MQ_DIVIDER_RATIO` to (R_top + R_bottom) / R_bottom.

**4-pin tactile button:** the four legs are two pairs that are always joined internally. Wire GPIO2 and GND to **diagonally opposite** legs. If the Serial Monitor prints `Saved baseline cleared` on every boot, the button reads as permanently pressed, so move one wire to the diagonal leg.

**What the button does** (one button, all handled in `buttons.cpp`):
| Action | Effect |
|---|---|
| Short press | next OLED screen: STATUS → SENSORS → VISION → NETWORK (also wakes the screen) |
| Hold 1.5 s during an alarm | silences the buzzer (5 min; 60 s during FIRE_CONFIRMED) and sends an acknowledge that cancels the simulated fire-department countdown |
| Hold 3 s while powering on | wipes the saved gas baseline (use after moving the device to a new room) |

## 2. Tools menu settings
| Setting | Value |
|---|---|
| Board | **ESP32S3 Dev Module** |
| USB CDC On Boot | **Disabled** |
| CPU Frequency | 240 MHz (WiFi) |
| Flash Mode | **DIO 80MHz** (QIO hung on large binaries during bring-up) |
| Flash Size | **16MB (128Mb)** |
| Partition Scheme | **Huge APP (3MB No OTA/1MB SPIFFS)** |
| PSRAM | **OPI PSRAM** (required: the models live in PSRAM) |
| Upload Mode | UART0 / Hardware CDC |
| Upload Speed | 921600 (drop to 460800 if uploads fail) |
| Port | the COM port of the board's **UART** USB-C port |

## 3. Upload
1. Open `firmware/esp32s3_cam_main/esp32s3_cam_main.ino` (all the `.cpp/.h` files must stay in that folder).
2. Plug the **UART** USB-C port into the PC. Leave the native "USB" port unplugged: GPIO20 is both I2C SDA and native-USB D+.
3. Click **Upload**. If it hangs at `Connecting...`, hold **BOOT**, tap **RST**, release BOOT, then upload again.
4. Serial Monitor at **115200** baud. Press **RST** to see the boot log.

## 4. microSD card (the quantized models)
1. Format the card **FAT32** (32 GB or smaller is safest).
2. Copy these two files from `firmware/` to the **root** of the card. Keep the names unchanged:
   - `fire_cnn_int8.tflite` (CNN: NO_FLAME / CONTROLLED_FLAME / HAZARDOUS_FIRE)
   - `fire_yolo_int8_160.tflite` (YOLO flame boxes)
3. Insert the card with the board powered off, then power on.

Expected boot log:
```
[vision] loaded /fire_cnn_int8.tflite (626904 bytes)
[vision] loaded /fire_yolo_int8_160.tflite (2929352 bytes)
[vision] CNN ready, arena ... KB
[vision] YOLO ready, arena ... KB
[vision] CNN + YOLO ready.
```
Each evidence snapshot then logs a line like `[vision] PRECURSOR: CONTROLLED_FLAME 87% (... ms) | 1 flame box(es) (... ms)`.
The OLED's third screen (short-press the info button) shows the same.

If the card or a file is missing, the log says `[vision] disabled: no SD card` (or `model file missing`). The alarm keeps working, and snapshots upload without on-device classification.

What the models do:
- Every evidence snapshot (on entering PRECURSOR / CONFIRMING / FIRE_CONFIRMED) and every stored on-demand snapshot is classified on the board.
- The result is uploaded with the photo, and the dashboard shows it as the snapshot's classification.
- A fresh `HAZARDOUS_FIRE` verdict at 80 % confidence or more can **raise** the risk score to CONFIRMING. It never lowers it. Set `VISION_AFFECTS_SCORE 0` in `config.h` to make vision advisory only.

## 5. Power (USB-C, no battery)
- Battery, TP4056, XL6009/MT3608 boost and INA219 are removed. The board runs from a **5 V / 2 A or better** USB-C adapter on the UART port.
- The MQ-2 / MQ-7 / MQ-135 heaters (about 450 mA together) take 5 V from the board's **5V pin**, which carries USB VBUS. Check it with a multimeter (about 4.8–5.0 V) before wiring the sensors.
- A laptop USB port (500–900 mA) can brown out when WiFi transmits. Use a wall adapter for real runs.
- Everything else (BME280, ADS1115, OLED, UV, flame, button) stays on 3V3 as before.

## 6. Bring everything up
1. Backend: `cd backend`.
   - The old `venv` was made on another PC and won't run. Recreate it: `python -m venv venv`, `venv\Scripts\activate`, `pip install -r requirements.txt`.
   - Then `python run.py`.
   - Allow Python through Windows Firewall on **Private** networks so the board can reach port 5000.
2. Dashboard: `cd dashboard`, `npm install` (first time), `npm run dev`, then open http://localhost:5173.
3. Power the board. Within about 10 s the backend log shows `POST /api/device/register`, and the device appears under **System**. Create a room there and assign the device.
