/*
 * camera.h — on-demand JPEG capture. Thread-safe: the web handler (main core)
 * and the network task (snapshot uploads) share the camera through a mutex that
 * is held from camera_capture() until camera_return_fb().
 */
#ifndef CAMERA_H
#define CAMERA_H

#include <Arduino.h>
#include "esp_camera.h"

bool camera_init();

// fresh=true discards one buffered frame first (fb_count=2 + GRAB_LATEST can hand back
// a stale frame after idle) — use for evidence snapshots. Returns nullptr on failure /
// if the camera is busy for >3 s. Caller MUST call camera_return_fb().
camera_fb_t* camera_capture(bool fresh);
void camera_return_fb(camera_fb_t* fb);

bool camera_is_online();
unsigned long camera_last_capture_ms();

#endif
