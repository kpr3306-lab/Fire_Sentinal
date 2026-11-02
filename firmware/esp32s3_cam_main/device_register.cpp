#include "device_register.h"
#include "config.h"
#include "network_client.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#if __has_include("esp_mac.h")
  #include "esp_mac.h"
#else
  #include "esp_system.h"
#endif

static char device_id[32] = {0};
static volatile bool force_pending = true;
static unsigned long next_announce_ms = 0;

void device_register_init() {
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);        // same value WiFi.macAddress() reports, but valid before WiFi.begin()
  snprintf(device_id, sizeof(device_id), "fs-%02X%02X%02X%02X%02X%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  Serial.printf("[register] device_id = %s\n", device_id);
}

const char* device_get_id() { return device_id; }

void device_register_force() { force_pending = true; }

static bool announce_now() {
  if (WiFi.status() != WL_CONNECTED) return false;

  JsonDocument doc;
  doc["device_id"]   = device_id;
  doc["device_name"] = DEVICE_NAME;
  doc["ip"]          = WiFi.localIP().toString();
  doc["port"]        = DEVICE_HTTP_PORT;
  doc["rssi"]        = WiFi.RSSI();
  String payload;
  serializeJson(doc, payload);

  String url = String("http://") + BACKEND_HOST + ":" + String(BACKEND_PORT) + BACKEND_REGISTER_PATH;
  HTTPClient http;
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(payload);
  http.end();

  if (code >= 200 && code < 300) {
    network_note_backend_ok();
    Serial.printf("[register] Announced OK: %s @ %s:%d\n", device_id, WiFi.localIP().toString().c_str(), DEVICE_HTTP_PORT);
    return true;
  }
  Serial.printf("[register] announce failed, code=%d (retry in %lus)\n", code, DEVICE_REGISTER_RETRY_MS / 1000UL);
  return false;
}

void device_register_tick(unsigned long now_ms) {
  if (!force_pending && (long)(now_ms - next_announce_ms) < 0) return;
  force_pending = false;
  next_announce_ms = now_ms + (announce_now() ? DEVICE_REGISTER_INTERVAL_MS : DEVICE_REGISTER_RETRY_MS);
}
