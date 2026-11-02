/*
 * config.h — Fire Sentinel Prototype 2 (firmware v2)
 * Board: Freenove ESP32-S3-WROOM CAM (N16R8, OPI PSRAM)
 *
 * Arduino IDE settings that matter (from bring-up):
 *   Board: ESP32S3 Dev Module | PSRAM: OPI PSRAM | Flash Mode: DIO 80MHz
 *   USB CDC On Boot: DISABLED | Partition: Huge APP
 *   (QIO flash mode and CDC-on-boot both caused silent boot hangs.)
 *   Serial output goes through the UART bridge port (GPIO43/44) — flash and
 *   monitor via the UART USB port, NOT the native USB port (GPIO19/20).
 */

#ifndef CONFIG_H
#define CONFIG_H

#if __has_include("secrets.h")
  #include "secrets.h"            // WIFI_SSID, WIFI_PASSWORD
#else
  #error "Missing secrets.h — copy secrets.h.example to secrets.h and fill in WIFI_SSID / WIFI_PASSWORD"
#endif

// ---------------------------------------------------------------------------
// Identity / backend
// ---------------------------------------------------------------------------
#define DEVICE_NAME "fire-sentinel-s3-01"

#define BACKEND_HOST "10.111.193.119"       // Flask server LAN IP
#define BACKEND_PORT 5000
#define BACKEND_REGISTER_PATH   "/api/device/register"
#define BACKEND_SENSOR_PATH     "/api/sensor-data"
#define BACKEND_SNAPSHOT_PATH   "/api/camera/snapshot"
#define DEVICE_REGISTER_INTERVAL_MS 60000UL
#define DEVICE_REGISTER_RETRY_MS    10000UL
#define DEVICE_HTTP_PORT 80

// ---------------------------------------------------------------------------
// Networking (all WiFi/HTTP work runs in its own task — see network_client.cpp)
// ---------------------------------------------------------------------------
#define WIFI_RETRY_INTERVAL_MS     10000UL
#define HTTP_CONNECT_TIMEOUT_MS    1500
#define HTTP_TIMEOUT_MS            3000
#define HTTP_SNAPSHOT_TIMEOUT_MS   6000
#define NET_FAILS_BEFORE_BACKOFF   3
#define NET_FAIL_BACKOFF_MS        5000UL
#define NET_QUEUE_LENGTH           8

// ---------------------------------------------------------------------------
// Camera pins — Freenove ESP32-S3-WROOM CAM (OV3660 on this unit)
// ---------------------------------------------------------------------------
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     15
#define SIOD_GPIO_NUM     4
#define SIOC_GPIO_NUM     5
#define Y2_GPIO_NUM       11
#define Y3_GPIO_NUM       9
#define Y4_GPIO_NUM       8
#define Y5_GPIO_NUM       10
#define Y6_GPIO_NUM       12
#define Y7_GPIO_NUM       18
#define Y8_GPIO_NUM       17
#define Y9_GPIO_NUM       16
#define VSYNC_GPIO_NUM    6
#define HREF_GPIO_NUM     7
#define PCLK_GPIO_NUM     13

#define WS2812_LED_GPIO   48

// microSD (SDMMC 1-bit) — holds the quantized vision models (vision.cpp)
#define SD_MMC_CLK_GPIO   39
#define SD_MMC_CMD_GPIO   38
#define SD_MMC_D0_GPIO    40

// ---------------------------------------------------------------------------
// Pins for the Prototype 2 wiring diagram (LEDs + diffuse button removed)
// ---------------------------------------------------------------------------
#define I2C_SDA_GPIO        20
#define I2C_SCL_GPIO        21
#define I2C_CLOCK_HZ        100000   // raise to 400000 only after the bus proves clean
#define FLAME_DIGITAL_GPIO  1
#define INFO_BUTTON_GPIO    2        // INPUT_PULLUP, other leg to GND
#define BUZZER_GPIO         42

// I2C addresses
#define BME280_FITTED     1          // 1 if a BME280 is wired; 0 = no temperature/humidity terms
#define BME280_I2C_ADDR   0x76       // falls back to 0x77
#define ADS1115_I2C_ADDR  0x48
#define OLED_I2C_ADDR     0x3C

// ADS1115 channels
#define ADS_CH_MQ2        0
#define ADS_CH_MQ7        1
#define ADS_CH_MQ135      2
#define ADS_CH_UV         3
#define MQ_DIVIDER_RATIO  2.0f       // 10k/10k divider in front of each MQ input

#define FLAME_ACTIVE_LOW  true       // verify on your module (LM393 DO normally pulls LOW on flame)

// ---------------------------------------------------------------------------
// Sampling — ONE fixed rate so window features mean the same thing in
// training and on the device. State only changes the *upload* cadence.
// ---------------------------------------------------------------------------
#define SENSOR_SAMPLE_INTERVAL_MS   1000UL
#define WINDOW_SIZE                 30        // samples (= 30 s at 1 Hz)

// Flame debounce: poll the pin fast, require FLAME_MIN_HITS of the last
// FLAME_HISTORY polls (i.e. ~40% duty over ~1 s). Real flames flicker.
#define FLAME_POLL_INTERVAL_MS      100UL
#define FLAME_HISTORY               10
#define FLAME_MIN_HITS              4

// Upload cadence
#define UPLOAD_INTERVAL_ELEVATED_MS       1000UL
#define HEARTBEAT_INTERVAL_MS             30000UL
#define ON_DEMAND_STORE_MIN_INTERVAL_MS   10000UL   // stops 1 fps Live View flooding the gallery

// ---------------------------------------------------------------------------
// Baseline (calibration) — see sensors.cpp
// ---------------------------------------------------------------------------
#define MQ_HEATER_WARMUP_MS             180000UL  // gas terms ignored until heaters settle (3 min)
#define BASELINE_WARMUP_SAMPLES         60        // quiet samples (after warm-up) before baseline is "ready"
#define BASELINE_EMA_SAMPLES            300       // slow tracking: ~5 min time constant
#define BASELINE_FREEZE_GAS_DEV         0.25f     // freeze learning if any MQ is >25% above baseline
#define BASELINE_FREEZE_TEMP_DEV_C      1.0f      // ...or temperature >1 C from baseline
#define BASELINE_ANCHOR_GAS_MAX_RATIO   1.6f      // baseline may never creep above 1.6x its anchor
#define BASELINE_ANCHOR_GAS_MIN_RATIO   0.5f
#define BASELINE_ANCHOR_TEMP_MAX_C      10.0f
#define BASELINE_SAVE_INTERVAL_MS       1800000UL // persist gas baseline to NVS every 30 min
#define BASELINE_NVS_VERSION            1
#define MQ_MIN_BASELINE_RAW             100.0f    // avoids divide-by-tiny

// ---------------------------------------------------------------------------
// Fusion (0-100). Non-flame max = 75 so CONFIRMING/FIRE are reachable
// without the flame sensor (smoldering fires).
// ---------------------------------------------------------------------------
#define FUSION_W_FLAME      35
#define FUSION_W_UV         10
#define FUSION_W_TEMP       25
#define FUSION_W_GAS        30
#define FUSION_W_GAS_AGREE  10

#define TEMP_FULL_DEV_C             5.0f     // +5 C over baseline = full temp points
#define TEMP_RATE_FULL_C_PER_MIN    6.0f     // +6 C/min = full temp points
#define TEMP_ABS_ELEVATED_C         45.0f    // 40% of temp points
#define TEMP_ABS_ALARM_C            57.0f    // fixed-temp heat-detector level -> score floor = CONFIRMING
#define GAS_FULL_DEV                1.5f     // +150% = full gas points
#define GAS_AGREE_DEV               0.4f     // >=2 sensors above +40% = agreement bonus
#define UV_FULL_SCALE_COUNTS        2400.0f  // ~0.3 V above baseline = full UV points
// Absolute fallbacks while baseline/heaters are not ready (raw ADS counts)
#define MQ2_ABS_ALARM_RAW           13100
#define MQ7_ABS_ALARM_RAW           16400

#define RISK_THRESHOLD_PRECURSOR   30
#define RISK_THRESHOLD_CONFIRMING  50
#define RISK_THRESHOLD_FIRE        65

// State machine timing
#define SUSTAINED_CONFIRM_WINDOW_MS  8000UL
#define PRECURSOR_COOLDOWN_MS        15000UL
#define FIRE_HOLD_MS                 30000UL

// ---------------------------------------------------------------------------
// Data logging + on-device sensor model
// ---------------------------------------------------------------------------
// One "CSV,..." line per sample on Serial (115200) — recorded by tools/collect_serial.py for training.
#define SERIAL_CSV_LOG              1
// 0 = the sensor model is ADVISORY (payload + serial log only). 1 = it may RAISE (never lower) the rule-based risk
// score. Leave at 0 until the model has been validated on real data.
#define SENSOR_ML_AFFECTS_SCORE     0
#define SENSOR_ML_MIN_CONFIDENCE    0.80f

// ---------------------------------------------------------------------------
// Buzzer (GPIO42). BUZZER_PASSIVE 1 = piezo/passive (tones), 0 = active module (on/off).
// BUZZER_LEDC_CHANNEL 0 -> timer 0. The camera is moved to timer 3/channel 7
// (camera.cpp) so tone() can never retune the camera XCLK.
// ---------------------------------------------------------------------------
#define BUZZER_PASSIVE            1
#define BUZZER_LEDC_CHANNEL       0
#define BUZZER_FREQ_PRECURSOR_HZ  2000
#define BUZZER_FREQ_CONFIRMING_HZ 2600
#define BUZZER_FREQ_FIRE_HZ       3200
#define BUZZER_SILENCE_MS         300000UL   // PRECURSOR / CONFIRMING: silenced for 5 min
#define BUZZER_SILENCE_FIRE_MS    60000UL    // FIRE_CONFIRMED: only 60 s, then it re-sounds

// Info button (GPIO2): short press = next OLED screen, long press = silence buzzer
#define BUTTON_DEBOUNCE_MS             30UL
#define BUTTON_LONG_PRESS_MS           1500UL
#define BUTTON_CLEAR_BASELINE_HOLD_MS  3000UL   // hold at power-up to wipe saved gas baseline

// OLED
#define DISPLAY_REFRESH_MS   1000UL
#define DISPLAY_SLEEP_MS     30000UL    // screen off after 30 s idle while NORMAL

// ---------------------------------------------------------------------------
// On-device vision (vision.cpp): quantized CNN + YOLO loaded from the microSD root.
// Power is a direct USB-C 5 V supply (no battery / boost / INA219).
// ---------------------------------------------------------------------------
#define VISION_CNN_PATH           "/fire_cnn_int8.tflite"
#define VISION_YOLO_PATH          "/fire_yolo_int8_160.tflite"
#define VISION_YOLO_CONF          0.25f     // same default as the backend detector
#define VISION_YOLO_NMS_IOU       0.45f
#define VISION_MAX_BOXES          5
#define VISION_PSRAM_RESERVE      (1024UL * 1024UL)   // left free for camera frames + uploads
// 1 = a fresh HAZARDOUS_FIRE classification may RAISE the score to CONFIRMING (never lowers it).
#define VISION_AFFECTS_SCORE      1
#define VISION_MIN_CONFIDENCE     0.80f
#define VISION_RESULT_MAX_AGE_MS  20000UL

#endif // CONFIG_H
