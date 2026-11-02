/*
 * camera.cpp — Fire Sentinel Prototype 2 (v2)
 * Freenove ESP32-S3-WROOM CAM. Works for OV2640 and OV3660 (JPEG).
 *
 * The camera XCLK uses LEDC timer 3 / channel 7 so the buzzer (channel 0 / timer 0)
 * can retune its own frequency with tone() without disturbing the camera clock.
 */

#include "camera.h"
#include "config.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static bool camera_online = false;
static unsigned long last_capture_ms = 0;
static SemaphoreHandle_t cam_mutex = nullptr;

bool camera_init() {
  if (cam_mutex == nullptr) cam_mutex = xSemaphoreCreateMutex();

  camera_config_t c = {};                       // zero-init: no stray garbage fields
  c.ledc_channel = LEDC_CHANNEL_7;
  c.ledc_timer   = LEDC_TIMER_3;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 10000000;                    // 20 MHz XCLK interferes with WiFi on this board (60%+ ping loss); stills don't need the fps
  c.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    c.frame_size   = FRAMESIZE_SVGA;
    c.jpeg_quality = 12;
    c.fb_count     = 2;
    c.fb_location  = CAMERA_FB_IN_PSRAM;
    c.grab_mode    = CAMERA_GRAB_LATEST;
  } else {
    Serial.println("[camera] WARNING: PSRAM not detected, using QVGA.");
    c.frame_size   = FRAMESIZE_QVGA;
    c.jpeg_quality = 15;
    c.fb_count     = 1;
    c.fb_location  = CAMERA_FB_IN_DRAM;
    c.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("[camera] ERROR: esp_camera_init failed 0x%x\n", err);
    camera_online = false;
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s) { s->set_vflip(s, 0); s->set_hmirror(s, 0); }
  camera_online = true;
  Serial.println("[camera] Initialized OK.");
  return true;
}

camera_fb_t* camera_capture(bool fresh) {
  if (cam_mutex == nullptr) return nullptr;
  if (xSemaphoreTake(cam_mutex, pdMS_TO_TICKS(3000)) != pdTRUE) {
    Serial.println("[camera] busy — capture skipped.");
    return nullptr;
  }
  camera_fb_t* fb = nullptr;
  if (fresh) {
    camera_fb_t* stale = esp_camera_fb_get();
    if (stale) esp_camera_fb_return(stale);
  }
  fb = esp_camera_fb_get();
  if (fb == nullptr) {
    Serial.println("[camera] ERROR: fb_get returned null.");
    camera_online = false;
    xSemaphoreGive(cam_mutex);
    return nullptr;
  }
  camera_online = true;
  last_capture_ms = millis();
  return fb;                                    // mutex stays held until camera_return_fb()
}

void camera_return_fb(camera_fb_t* fb) {
  if (fb != nullptr) {
    esp_camera_fb_return(fb);
    if (cam_mutex) xSemaphoreGive(cam_mutex);
  }
}

bool camera_is_online() { return camera_online; }
unsigned long camera_last_capture_ms() { return last_capture_ms; }
