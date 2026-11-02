/*
 * network_client.cpp — Fire Sentinel Prototype 2 (v2)
 * Library: ArduinoJson v7.
 *
 * Failure behaviour: short HTTP timeouts; after NET_FAILS_BEFORE_BACKOFF consecutive
 * failures jobs are dropped (not retried) for NET_FAIL_BACKOFF_MS so a dead backend
 * costs almost nothing. Dropped uploads are not buffered (SD buffering = Phase 2).
 */

#include "network_client.h"
#include "config.h"
#include "camera.h"
#include "device_register.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_heap_caps.h"

enum class JobType : uint8_t { SENSOR, SNAPSHOT };

struct NetJob {
  JobType type;
  SensorReading reading;
  FusionResult fusion;
  FireState state;
  WindowStats window;
  SensorMlResult ml;
  bool silenced;
  uint32_t ack_seq;
  bool fresh;
  char reason[24];
  uint8_t* jpeg;            // pre-captured frame owned by the job, or nullptr = capture at send time
  size_t jpeg_len;
  VisionResult vis;
};

static void drop_job(NetJob& j) { if (j.jpeg) { free(j.jpeg); j.jpeg = nullptr; } }

static QueueHandle_t job_queue = nullptr;
static volatile unsigned long last_backend_ok_ms = 0;
static int consecutive_failures = 0;
static unsigned long backoff_until_ms = 0;

static String backend_url(const char* path) {
  return String("http://") + BACKEND_HOST + ":" + String(BACKEND_PORT) + path;
}

bool network_is_connected() { return WiFi.status() == WL_CONNECTED; }

void network_note_backend_ok() { last_backend_ok_ms = millis(); if (last_backend_ok_ms == 0) last_backend_ok_ms = 1; }

bool network_backend_ok() {
  unsigned long t = last_backend_ok_ms;
  return t != 0 && (millis() - t) < 90000UL;
}

static void note_result(bool ok, unsigned long now_ms) {
  if (ok) { consecutive_failures = 0; network_note_backend_ok(); return; }
  if (++consecutive_failures >= NET_FAILS_BEFORE_BACKOFF) {
    backoff_until_ms = now_ms + NET_FAIL_BACKOFF_MS;
    consecutive_failures = 0;
    Serial.println("[network] backend unreachable — backing off.");
  }
}

// ---------------------------------------------------------------------------
// Job handlers (run inside the network task)
// ---------------------------------------------------------------------------
static bool post_sensor(const NetJob& j) {
  JsonDocument doc;
  doc["device_id"]    = device_get_id();
  doc["timestamp_ms"] = j.reading.timestamp_ms;
  doc["state"]        = state_machine_state_name(j.state);
  doc["risk_score"]   = j.fusion.risk_score;
  doc["buzzer_silenced"] = j.silenced;
  doc["ack_seq"]         = j.ack_seq;       // +1 per long-press while elevated (backend: cancels dispatch countdown)
  doc["sensor_fault"]    = j.fusion.sensor_fault;

  JsonObject s = doc["sensors"].to<JsonObject>();
  s["temperature_c"]  = j.reading.temperature_c;
  s["humidity_pct"]   = j.reading.humidity_pct;
  s["pressure_hpa"]   = j.reading.pressure_hpa;
  s["mq2_ppm"]        = j.reading.mq2_ppm_est;      // placeholder estimates (kept for the dashboard)
  s["mq7_ppm"]        = j.reading.mq7_ppm_est;
  s["mq135_ppm"]      = j.reading.mq135_ppm_est;
  s["uv_index"]       = j.reading.uv_index_est;
  s["mq2_raw"]        = j.reading.mq2_raw;          // use these for ML training
  s["mq7_raw"]        = j.reading.mq7_raw;
  s["mq135_raw"]      = j.reading.mq135_raw;
  s["uv_raw"]         = j.reading.uv_raw;
  s["flame_detected"] = j.reading.flame_detected;
  s["reading_valid"]  = j.reading.valid;

  JsonObject f = doc["fusion"].to<JsonObject>();
  f["temp_deviation"]      = j.fusion.temp_deviation;
  f["temp_rate_c_per_min"] = j.fusion.temp_rate_c_per_min;
  f["gas_deviation_pct"]   = j.fusion.gas_deviation_pct;
  f["gas_agree_count"]     = j.fusion.gas_agree_count;
  f["gas_terms_active"]    = j.fusion.gas_terms_active;

  if (j.ml.valid) {
    JsonObject m = doc["ml"].to<JsonObject>();
    m["class"]     = sensor_ml_class_name(j.ml.cls);
    m["conf"]      = j.ml.conf;
    m["anomaly"]   = j.ml.anomaly;
    m["anomalous"] = j.ml.anomalous;
    m["version"]   = sensor_ml_version();
  }

  if (j.window.ready) {
    JsonObject w = doc["window"].to<JsonObject>();
    for (int c = 0; c < WCH_COUNT; c++) {
      JsonObject ch = w[WINDOW_CHANNEL_NAMES[c]].to<JsonObject>();
      ch["mean"] = j.window.mean[c];
      ch["std"]  = j.window.stddev[c];
      ch["slope_per_s"] = j.window.slope_per_s[c];
    }
  }

  String payload;
  serializeJson(doc, payload);

  HTTPClient http;
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.begin(backend_url(BACKEND_SENSOR_PATH));
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(payload);
  http.end();
  if (code <= 0) { Serial.printf("[network] sensor POST failed, code=%d\n", code); return false; }
  return code >= 200 && code < 300;
}

static String form_field(const String& boundary, const char* name, const String& value) {
  return "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name + "\"\r\n\r\n" + value + "\r\n";
}

static bool post_snapshot(const NetJob& j) {
  camera_fb_t* fb = nullptr;
  if (j.jpeg == nullptr) {                       // plain snapshot: capture now (vision off / busy)
    fb = camera_capture(j.fresh);
    if (fb == nullptr) return false;
  }
  const uint8_t* img = fb ? fb->buf : j.jpeg;
  const size_t img_len = fb ? fb->len : j.jpeg_len;

  const String boundary = "FireSentinelBoundary7331";
  String head = form_field(boundary, "device_id", device_get_id()) + form_field(boundary, "reason", j.reason);
  if (j.vis.valid) {                             // on-device CNN / YOLO result (backend falls back to it)
    String boxes = "[";
    for (int i = 0; i < j.vis.n_boxes; i++) {
      const float* b = j.vis.boxes[i];
      boxes += String(i ? "," : "") + "[" + String(b[0], 4) + "," + String(b[1], 4) + "," + String(b[2], 4) + "," +
               String(b[3], 4) + "," + String(b[4], 3) + "]";
    }
    head += form_field(boundary, "cnn_class", vision_class_name(j.vis.cnn_cls)) +
            form_field(boundary, "cnn_conf", String(j.vis.cnn_conf, 3));
    if (j.vis.yolo_ok) head += form_field(boundary, "yolo_boxes", boxes + "]");   // absent = detector did not run
  }
  head += "--" + boundary + "\r\n"
          "Content-Disposition: form-data; name=\"image\"; filename=\"snapshot.jpg\"\r\n"
          "Content-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";

  size_t total = head.length() + img_len + tail.length();
  uint8_t* body = (uint8_t*)heap_caps_malloc(total, MALLOC_CAP_SPIRAM);   // prefer PSRAM
  if (body == nullptr) body = (uint8_t*)malloc(total);
  if (body == nullptr) {
    Serial.println("[network] not enough memory for multipart body.");
    camera_return_fb(fb);
    return false;
  }
  memcpy(body, head.c_str(), head.length());
  memcpy(body + head.length(), img, img_len);
  memcpy(body + head.length() + img_len, tail.c_str(), tail.length());
  camera_return_fb(fb);                          // frame copied — release the camera before the slow upload

  HTTPClient http;
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_SNAPSHOT_TIMEOUT_MS);
  http.begin(backend_url(BACKEND_SNAPSHOT_PATH));
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  int code = http.POST(body, total);
  http.end();
  free(body);

  if (code <= 0) { Serial.printf("[network] snapshot POST failed, code=%d\n", code); return false; }
  return code >= 200 && code < 300;
}

// ---------------------------------------------------------------------------
// The network task
// ---------------------------------------------------------------------------
static void net_task(void*) {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   // modem sleep misses the PC's ARP requests on phone hotspots -> replies never arrive (code=-1)
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[network] Connecting to '%s' (non-blocking)...\n", WIFI_SSID);

  bool was_connected = false;
  unsigned long last_attempt_ms = millis();

  for (;;) {
    unsigned long now = millis();
    bool connected = (WiFi.status() == WL_CONNECTED);

    if (connected && !was_connected) {
      Serial.printf("[network] Connected. IP: %s\n", WiFi.localIP().toString().c_str());
      device_register_force();
    } else if (!connected && was_connected) {
      Serial.println("[network] WiFi lost.");
    }
    if (!connected && (now - last_attempt_ms) >= WIFI_RETRY_INTERVAL_MS) {
      last_attempt_ms = now;
      // 1 = SSID not seen (5 GHz / out of range), 4 = rejected (password), 6 = still trying
      Serial.printf("[network] WiFi not connected (status %d), retrying...\n", (int)WiFi.status());
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    was_connected = connected;

    NetJob job;
    if (xQueueReceive(job_queue, &job, pdMS_TO_TICKS(200)) == pdTRUE) {
      now = millis();
      bool in_backoff = (long)(backoff_until_ms - now) > 0;
      if (connected && !in_backoff) {
        bool ok = (job.type == JobType::SENSOR) ? post_sensor(job) : post_snapshot(job);
        note_result(ok, millis());
      }
      // else: dropped (offline / backing off) — the next sample supersedes it
      drop_job(job);
    }
    if (connected) device_register_tick(millis());
  }
}

void network_init() {
  job_queue = xQueueCreate(NET_QUEUE_LENGTH, sizeof(NetJob));
  xTaskCreatePinnedToCore(net_task, "net", 12288, nullptr, 1, nullptr, 0);
}

bool network_enqueue_sensor(const SensorReading& r, const FusionResult& f, FireState s,
                            const WindowStats& w,
                            bool buzzer_silenced, uint32_t ack_seq,
                            const SensorMlResult& ml, bool important) {
  if (job_queue == nullptr) return false;
  NetJob j = {};
  j.type = JobType::SENSOR;
  j.reading = r; j.fusion = f; j.state = s; j.window = w;
  j.silenced = buzzer_silenced;
  j.ack_seq = ack_seq;
  j.ml = ml;
  if (xQueueSend(job_queue, &j, 0) == pdTRUE) return true;
  if (important) {
    NetJob dump;
    if (xQueueReceive(job_queue, &dump, 0) == pdTRUE) drop_job(dump);   // evict oldest
    return xQueueSend(job_queue, &j, 0) == pdTRUE;
  }
  return false;
}

static bool enqueue_snapshot(const NetJob& j) {
  if (job_queue == nullptr) return false;
  if (xQueueSend(job_queue, &j, 0) == pdTRUE) return true;
  if (strcmp(j.reason, "on_demand") != 0) {      // evidence snapshots evict the oldest job; on-demand ones just drop
    NetJob dump;
    if (xQueueReceive(job_queue, &dump, 0) == pdTRUE) drop_job(dump);
    return xQueueSend(job_queue, &j, 0) == pdTRUE;
  }
  return false;
}

bool network_request_snapshot(const char* reason, bool fresh_frame) {
  NetJob j = {};
  j.type = JobType::SNAPSHOT;
  j.fresh = fresh_frame;
  strncpy(j.reason, reason, sizeof(j.reason) - 1);
  return enqueue_snapshot(j);
}

bool network_enqueue_snapshot_jpeg(const char* reason, uint8_t* jpeg, size_t len, const VisionResult& vis) {
  NetJob j = {};
  j.type = JobType::SNAPSHOT;
  j.jpeg = jpeg; j.jpeg_len = len; j.vis = vis;
  strncpy(j.reason, reason, sizeof(j.reason) - 1);
  return enqueue_snapshot(j);
}
