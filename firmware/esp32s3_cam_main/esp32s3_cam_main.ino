/*
 * esp32s3_cam_main.ino — Fire Sentinel (firmware v2)
 * Board: Freenove ESP32-S3-WROOM CAM (N16R8)
 *
 * Arduino IDE settings (all confirmed during bring-up):
 *   Board: ESP32S3 Dev Module | PSRAM: OPI PSRAM | Flash Mode: DIO 80MHz
 *   USB CDC On Boot: Disabled | Partition Scheme: Huge APP | Flash Size: 16MB
 *   Flash/monitor through the UART USB port (GPIO43/44). Do not plug the native USB
 *   port while the I2C bus is on GPIO20.
 *
 * Libraries (Library Manager):
 *   Adafruit BME280 (+ Adafruit Unified Sensor), Adafruit ADS1X15,
 *   Adafruit SSD1306 (+ Adafruit GFX), ArduinoJson v7
 *   (TensorFlow Lite Micro + esp_jpeg for vision.cpp ship with the ESP32 core — nothing to install)
 *
 * microSD (FAT32) root: fire_cnn_int8.tflite + fire_yolo_int8_160.tflite (copy from firmware/).
 *
 * Setup: copy secrets.h.example -> secrets.h and fill in WiFi credentials.
 *
 * Architecture
 *   loop() (core 1) : sensors @ fixed 1 Hz, fusion, state machine, buzzer, OLED, button.
 *                     NEVER waits on the network.
 *   net task (core 0): WiFi reconnect, sensor/snapshot uploads, device registration.
 *   http task (core 0): local web server (/capture, /status).
 *
 * Info button (GPIO2): short press = next OLED screen, long press = silence buzzer,
 *                      hold at power-up = clear saved gas baseline.
 */

#include <WiFi.h>
#include <WebServer.h>

#include "config.h"
#include "sensors.h"
#include "window.h"
#include "camera.h"
#include "fusion.h"
#include "state_machine.h"
#include "network_client.h"
#include "device_register.h"
#include "vision.h"
#include "buzzer.h"
#include "buttons.h"
#include "display.h"
#include "sensor_ml.h"
#include "sensor_model.h"

static WebServer server(DEVICE_HTTP_PORT);

static unsigned long last_sample_ms = 0;
static unsigned long last_upload_ms = 0;
static unsigned long last_on_demand_store_ms = 0;
static bool on_demand_store_seen = false;

static UiSnapshot ui = {};

static bool request_snapshot(const char* reason) {
  return vision_request(reason) || network_request_snapshot(reason, true);
}
static uint32_t ack_seq = 0;            // incremented on every long press while elevated
static unsigned long last_ack_ms = 0;

// ---------------------------------------------------------------------------
// Local HTTP handlers (dashboard-facing)
// ---------------------------------------------------------------------------
static void handle_capture() {
  camera_fb_t* fb = camera_capture(false);          // live view: speed over freshness
  if (fb == nullptr) {
    server.send(503, "text/plain", "Camera capture failed");
    return;
  }
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  WiFiClient client = server.client();
  client.write(fb->buf, fb->len);
  camera_return_fb(fb);

  // Keep a record of on-demand pulls, but at most once per ON_DEMAND_STORE_MIN_INTERVAL_MS
  // (1 fps Live View would otherwise flood the gallery). ?store=0 disables it entirely.
  bool store = !(server.hasArg("store") && server.arg("store") == "0");
  unsigned long now = millis();
  if (store && (!on_demand_store_seen || now - last_on_demand_store_ms >= ON_DEMAND_STORE_MIN_INTERVAL_MS)) {
    if (request_snapshot("on_demand")) {
      last_on_demand_store_ms = now;
      on_demand_store_seen = true;
    }
  }
}

static void handle_status() {
  unsigned long now = millis();
  String json = "{";
  json += "\"device_id\":\"" + String(device_get_id()) + "\",";
  json += "\"camera_online\":" + String(camera_is_online() ? "true" : "false") + ",";
  json += "\"wifi_connected\":" + String(network_is_connected() ? "true" : "false") + ",";
  json += "\"state\":\"" + String(state_machine_state_name(state_machine_get_state())) + "\",";
  json += "\"buzzer_silenced\":" + String(buzzer_is_silenced(now) ? "true" : "false") + ",";
  json += "\"vision\":\"" + String(vision_status()) + "\",";
  json += "\"uptime_ms\":" + String(now);
  json += "}";
  server.send(200, "application/json", json);
}

// Own task: a client.write() to a slow or stalled client can block for tens of seconds,
// which must never freeze sensing and the alarm in loop().
static void http_task(void*) {
  for (;;) {
    server.handleClient();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

// ---------------------------------------------------------------------------
// setup
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[boot] Fire Sentinel firmware v2 starting...");
  Serial.printf("[boot] sensor model: %s%s\n", sensor_ml_available() ? sensor_ml_version() : "none (rule-based only)",
                sensor_ml_available() && SENSOR_MODEL_SYNTHETIC ? "  *** SYNTHETIC — test only ***" : "");
#if SERIAL_CSV_LOG
  Serial.println("CSV_HEADER,ms,temp,hum,pres,mq2,mq7,mq135,uv,flame,valid,state,risk,b_temp,b_mq2,b_mq7,b_mq135,b_uv,b_ready");
#endif

  buttons_init();
  bool clear_baseline = buttons_held_at_boot(BUTTON_CLEAR_BASELINE_HOLD_MS);
  if (clear_baseline) sensors_clear_saved_baseline();

  if (!sensors_init()) Serial.println("[boot] WARNING: a sensor failed to initialise — running degraded, will retry.");
  display_init();
  buzzer_init();
  buzzer_boot_chirp();
  display_splash(clear_baseline ? "Baseline cleared" : "Booting...", "MQ warm-up: 3 min");

  if (!camera_init()) Serial.println("[boot] ERROR: camera init failed — vision evidence unavailable.");

  device_register_init();                 // device_id from MAC (no network)
  network_init();                         // WiFi + uploads run in their own task; setup does not wait
  vision_init();                          // SD + model loading in its own task; snapshots work without it

  server.on("/capture", HTTP_GET, handle_capture);
  server.on("/status", HTTP_GET, handle_status);
  server.begin();                         // always started — works whenever WiFi comes up
  xTaskCreatePinnedToCore(http_task, "http", 8192, nullptr, 1, nullptr, 0);
  Serial.printf("[server] HTTP server on port %d\n", DEVICE_HTTP_PORT);

  Serial.println("[boot] Setup complete. Detection is running; WiFi connects in the background.");
}

// ---------------------------------------------------------------------------
// loop — every step is non-blocking except one sensor read (~40 ms) per second
// and an OLED redraw (~90 ms at 100 kHz I2C, at most once per second)
// ---------------------------------------------------------------------------
void loop() {
  unsigned long now = millis();

  sensors_flame_poll(now);

  switch (buttons_poll(now)) {
    case ButtonEvent::SHORT_PRESS: display_next_screen(now); break;
    case ButtonEvent::LONG_PRESS:
      buzzer_silence(now);
      display_wake(now);
      if (state_machine_get_state() != FireState::NORMAL) {
        ack_seq++;                       // backend treats an increase as "a human is on site" -> cancels dispatch countdown
        last_ack_ms = now;
      }
      last_upload_ms = 0;                // force the next sample cycle to upload right away
      Serial.printf("[button] long press: buzzer silenced, ack_seq=%lu\n", (unsigned long)ack_seq);
      break;
    default: break;
  }

  if (now - last_sample_ms >= SENSOR_SAMPLE_INTERVAL_MS) {
    last_sample_ms = now;

    SensorReading reading = sensors_read();
    if (reading.valid) window_push(reading); else window_reset();
    WindowStats window = window_compute();

    SensorBaseline baseline = sensors_get_baseline();
    SensorMlResult ml = sensor_ml_infer(window, baseline, now);

    FusionResult fusion = fusion_compute(reading, baseline, window);
#if SENSOR_ML_AFFECTS_SCORE
    // The model may only RAISE the rule-based score (rules stay the safety floor).
    if (ml.valid) {
      if (ml.cls == 2 && ml.conf >= SENSOR_ML_MIN_CONFIDENCE && fusion.risk_score < RISK_THRESHOLD_CONFIRMING)
        fusion.risk_score = RISK_THRESHOLD_CONFIRMING;
      else if (ml.anomalous && fusion.risk_score < RISK_THRESHOLD_PRECURSOR)
        fusion.risk_score = RISK_THRESHOLD_PRECURSOR;
    }
#endif
#if VISION_AFFECTS_SCORE
    {
      // A fresh camera verdict of HAZARDOUS_FIRE may only RAISE the score to CONFIRMING (rules stay the floor).
      VisionResult v = vision_latest();
      if (v.valid && millis() - v.at_ms < VISION_RESULT_MAX_AGE_MS && v.cnn_cls == 2 &&
          v.cnn_conf >= VISION_MIN_CONFIDENCE && fusion.risk_score < RISK_THRESHOLD_CONFIRMING)
        fusion.risk_score = RISK_THRESHOLD_CONFIRMING;
    }
#endif
    StateMachineOutput sm = state_machine_update(fusion, now);

#if SERIAL_CSV_LOG
    {
      bool ready = baseline.temp_ready && baseline.gas_ready && (now >= MQ_HEATER_WARMUP_MS);
      Serial.printf("CSV,%lu,%.3f,%.2f,%.2f,%d,%d,%d,%d,%d,%d,%s,%d,%.3f,%.1f,%.1f,%.1f,%.1f,%d\n",
        now, reading.temperature_c, reading.humidity_pct, reading.pressure_hpa,
        reading.mq2_raw, reading.mq7_raw, reading.mq135_raw, reading.uv_raw,
        reading.flame_detected ? 1 : 0, reading.valid ? 1 : 0,
        state_machine_state_name(sm.current_state), fusion.risk_score,
        baseline.temp_baseline_c, baseline.mq2_baseline, baseline.mq7_baseline, baseline.mq135_baseline,
        baseline.uv_baseline, ready ? 1 : 0);
    }
#endif

    // Learn the baseline only while NORMAL (and the baseline freezes itself on drift)
    if (sm.current_state == FireState::NORMAL) sensors_update_baseline(reading, now);

    buzzer_set_state(sm.current_state, now);

    if (sm.state_changed_this_cycle) {
      Serial.printf("[state] -> %s (risk=%d flame=%d temp_dev=%.1f rate=%.1fC/min gas_dev=%.0f%% agree=%d)\n",
        state_machine_state_name(sm.current_state), fusion.risk_score, fusion.flame_signal,
        fusion.temp_deviation, fusion.temp_rate_c_per_min, fusion.gas_deviation_pct, fusion.gas_agree_count);
    }

    if (sm.camera_trigger_requested) {
      request_snapshot(state_machine_state_name(sm.current_state));
    }

    bool elevated = sm.current_state != FireState::NORMAL;
    bool due = sm.state_changed_this_cycle ||
               (elevated  && now - last_upload_ms >= UPLOAD_INTERVAL_ELEVATED_MS) ||
               (!elevated && now - last_upload_ms >= HEARTBEAT_INTERVAL_MS);
    if (due) {
      network_enqueue_sensor(reading, fusion, sm.current_state, window,
                             buzzer_is_silenced(now), ack_seq, ml, sm.state_changed_this_cycle);
      last_upload_ms = now;
    }

    // Snapshot for the OLED
    ui.state = sm.current_state;
    ui.risk = fusion.risk_score;
    ui.flame = reading.flame_detected;
    ui.sensor_fault = fusion.sensor_fault;
    ui.temp_c = reading.temperature_c; ui.hum_pct = reading.humidity_pct; ui.pres_hpa = reading.pressure_hpa;
    ui.mq2_raw = reading.mq2_raw; ui.mq7_raw = reading.mq7_raw;
    ui.mq135_raw = reading.mq135_raw; ui.uv_raw = reading.uv_raw;
  }

  ui.buzzer_silenced = buzzer_is_silenced(now);
  ui.ack_recent = (last_ack_ms != 0) && (now - last_ack_ms < 5000UL);
  buzzer_tick(now);
  display_tick(now, ui);
}
