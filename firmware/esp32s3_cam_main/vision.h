/*
 * vision.h — on-device CNN (NO_FLAME / CONTROLLED_FLAME / HAZARDOUS_FIRE) + YOLO flame boxes.
 * Models are the quantized .tflite files on the microSD root (see config.h VISION_*_PATH), loaded
 * into PSRAM by the vision task. Uses the TensorFlow Lite Micro + esp_jpeg built into the ESP32 core.
 *
 * Every evidence / on-demand snapshot goes through the vision task: capture -> classify -> detect ->
 * upload (with the results as extra form fields). If the SD card or a model is missing, vision_request()
 * returns false and the caller falls back to a plain snapshot upload — detection never depends on it.
 */
#ifndef VISION_H
#define VISION_H

#include <Arduino.h>
#include "config.h"

struct VisionResult {
  bool  valid;
  unsigned long at_ms;
  int   cnn_cls;                          // 0 NO_FLAME, 1 CONTROLLED_FLAME, 2 HAZARDOUS_FIRE
  float cnn_conf;
  uint32_t cnn_ms;
  bool  yolo_ok;                          // false: YOLO not loaded / failed, boxes mean nothing
  int   n_boxes;
  float boxes[VISION_MAX_BOXES][5];       // x1,y1,x2,y2 (0-1 of the frame), score
  uint32_t yolo_ms;
};

void vision_init();                       // starts the task; SD + model loading happen there (non-blocking)
bool vision_ready();
const char* vision_status();              // short human-readable state for OLED / serial
bool vision_request(const char* reason);  // queue capture+inference+upload; false if not ready / busy
VisionResult vision_latest();
const char* vision_class_name(int cls);

#endif
