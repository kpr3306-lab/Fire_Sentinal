/*
 * window.h — fixed-rate ring buffer of the last WINDOW_SIZE valid samples and
 * the window features (mean / std / slope-per-second) per channel. Used for the
 * rate-of-rise terms in fusion, and is the feature source for the Random Forest /
 * dense classifier and the anomaly detector (same numbers on device and in training
 * as long as SENSOR_SAMPLE_INTERVAL_MS stays fixed).
 */
#ifndef WINDOW_H
#define WINDOW_H

#include "sensors.h"

enum WindowChannel { WCH_TEMP = 0, WCH_MQ2, WCH_MQ7, WCH_MQ135, WCH_UV, WCH_FLAME, WCH_COUNT };
extern const char* const WINDOW_CHANNEL_NAMES[WCH_COUNT];

struct WindowStats {
  bool  ready;                  // true once WINDOW_SIZE valid samples are buffered
  int   n;
  float mean[WCH_COUNT];
  float stddev[WCH_COUNT];
  float slope_per_s[WCH_COUNT]; // least-squares slope, units per second
};

void window_push(const SensorReading& r);   // only call with r.valid == true
void window_reset();                        // call on an invalid read (a gap breaks the fixed-rate assumption)
WindowStats window_compute();

#endif
