#include "display.h"
#include "config.h"
#include "i2c_util.h"
#include "network_client.h"
#include "device_register.h"
#include "vision.h"
#include <WiFi.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

static Adafruit_SSD1306 oled(128, 64, &Wire, -1);
static bool oled_ok = false;
static bool oled_on = true;
static int  screen = 0;
static const int N_SCREENS = 4;
static unsigned long last_draw_ms = 0, last_wake_ms = 0, last_reinit_ms = 0;
static bool force_draw = true;

bool display_init() {
  oled_ok = oled.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR);
  if (!oled_ok) { Serial.println("[display] SSD1306 not responding."); return false; }
  oled.clearDisplay(); oled.display();
  last_wake_ms = millis();
  return true;
}

void display_splash(const char* l1, const char* l2) {
  if (!oled_ok) return;
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(1);
  oled.setCursor(0, 8);  oled.println("FIRE SENTINEL P2");
  oled.setCursor(0, 28); oled.println(l1);
  oled.setCursor(0, 40); oled.println(l2);
  oled.display();
  delay(1000);
}

void display_wake(unsigned long now_ms) {
  last_wake_ms = now_ms;
  if (oled_ok && !oled_on) { oled.ssd1306_command(SSD1306_DISPLAYON); oled_on = true; }
  force_draw = true;
}

void display_next_screen(unsigned long now_ms) {
  screen = (screen + 1) % N_SCREENS;
  display_wake(now_ms);
}

static const char* short_state(FireState s) {
  switch (s) {
    case FireState::NORMAL: return "NORMAL";
    case FireState::PRECURSOR: return "PRECURSOR";
    case FireState::CONFIRMING: return "CONFIRMING";
    case FireState::FIRE_CONFIRMED: return "FIRE!";
  }
  return "?";
}

static void draw_status(const UiSnapshot& ui) {
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.printf("WiFi:%s Srv:%s%s", network_is_connected() ? "OK" : "--",
              network_backend_ok() ? "OK" : "--", ui.sensor_fault ? " FLT" : "");
  oled.setTextSize(2);
  oled.setCursor(0, 14);
  oled.print(short_state(ui.state));
  oled.drawRect(0, 36, 128, 8, SSD1306_WHITE);
  int w = (ui.risk * 124) / 100;
  oled.fillRect(2, 38, w < 0 ? 0 : (w > 124 ? 124 : w), 4, SSD1306_WHITE);
  oled.setTextSize(1);
  oled.setCursor(0, 47);
  oled.printf("Risk %d/100%s", ui.risk, ui.flame ? "  FLAME" : "");
  oled.setCursor(0, 56);
  if (ui.state != FireState::NORMAL) oled.print(ui.ack_recent ? "ACK SENT to server" : (ui.buzzer_silenced ? "Buzzer SILENCED" : "Hold btn: ack"));
  else oled.print("Btn: next screen");
}

static void draw_sensors(const UiSnapshot& ui) {
  oled.setTextSize(1);
  oled.setCursor(0, 0);  oled.print("SENSORS");
#if BME280_FITTED
  oled.setCursor(0, 12); oled.printf("T %.1fC  H %.0f%%", ui.temp_c, ui.hum_pct);
  oled.setCursor(0, 22); oled.printf("P %.0f hPa", ui.pres_hpa);
#else
  oled.setCursor(0, 12); oled.print("T/H/P: no BME280");
#endif
  oled.setCursor(0, 32); oled.printf("MQ2 %-5d MQ7 %-5d", ui.mq2_raw, ui.mq7_raw);
  oled.setCursor(0, 42); oled.printf("MQ135 %-5d UV %d", ui.mq135_raw, ui.uv_raw);
  oled.setCursor(0, 54); oled.printf("Flame: %s", ui.flame ? "YES" : "no");
}

static void draw_vision(const UiSnapshot& ui) {
  (void)ui;
  oled.setTextSize(1);
  oled.setCursor(0, 0); oled.print("VISION (SD models)");
  oled.setCursor(0, 12); oled.printf("Status: %s", vision_status());
  VisionResult v = vision_latest();
  if (!v.valid) { oled.setCursor(0, 26); oled.print("No frame analysed yet"); return; }
  oled.setCursor(0, 24); oled.print(vision_class_name(v.cnn_cls));
  oled.setCursor(0, 34); oled.printf("CNN %.0f%%  %lu ms", v.cnn_conf * 100, (unsigned long)v.cnn_ms);
  oled.setCursor(0, 44);
  if (v.yolo_ok) oled.printf("YOLO %d box  %lu ms", v.n_boxes, (unsigned long)v.yolo_ms);
  else oled.print("YOLO off");
  oled.setCursor(0, 54); oled.printf("%lus ago", (millis() - v.at_ms) / 1000UL);
}

static void draw_network(const UiSnapshot& ui) {
  (void)ui;
  oled.setTextSize(1);
  oled.setCursor(0, 0);  oled.print("NETWORK");
  oled.setCursor(0, 12); oled.printf("WiFi: %s", network_is_connected() ? "connected" : "DOWN");
  oled.setCursor(0, 22); oled.print(WiFi.localIP().toString());
  oled.setCursor(0, 32); oled.printf("RSSI %d dBm", WiFi.RSSI());
  oled.setCursor(0, 42); oled.printf("Backend: %s", network_backend_ok() ? "OK" : "no reply");
  oled.setCursor(0, 54); oled.printf("Up %lus", millis() / 1000UL);
}

void display_tick(unsigned long now_ms, const UiSnapshot& ui) {
  if (!oled_ok) {                                          // slow retry if it was missing at boot
    if (now_ms - last_reinit_ms >= 10000UL) { last_reinit_ms = now_ms; if (i2c_ping(OLED_I2C_ADDR)) display_init(); }
    return;
  }

  bool elevated = ui.state != FireState::NORMAL;
  if (elevated) { if (screen != 0) { screen = 0; force_draw = true; } display_wake(now_ms); }

  if (oled_on && !elevated && (now_ms - last_wake_ms) >= DISPLAY_SLEEP_MS) {
    oled.ssd1306_command(SSD1306_DISPLAYOFF);
    oled_on = false;
  }
  if (!oled_on) return;

  if (!force_draw && (now_ms - last_draw_ms) < DISPLAY_REFRESH_MS) return;
  force_draw = false;
  last_draw_ms = now_ms;

  if (!i2c_ping(OLED_I2C_ADDR)) { oled_ok = false; return; }   // lost at runtime
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  switch (screen) {
    case 0: draw_status(ui);  break;
    case 1: draw_sensors(ui); break;
    case 2: draw_vision(ui);  break;
    default: draw_network(ui);
  }
  oled.display();
}
