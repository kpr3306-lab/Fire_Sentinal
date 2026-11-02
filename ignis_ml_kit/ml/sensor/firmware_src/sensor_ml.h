/*
 * sensor_ml.h — on-device sensor model: RandomForest class + IsolationForest anomaly score.
 *
 * Input  : the 30 s window statistics (window.cpp) and the current baseline (sensors.cpp) — the SAME 16
 *          baseline-relative features that ml/sensor/sensor_common.py builds during training.
 * Output : class (NORMAL / CONTROLLED_FLAME / HAZARDOUS_FIRE) + confidence, and a "not normal" anomaly flag.
 * Status : ADVISORY by default (SENSOR_ML_AFFECTS_SCORE 0 in config.h): published in the payload and logged,
 *          it does not change the alarm state until you have validated it on real data.
 */
#ifndef SENSOR_ML_H
#define SENSOR_ML_H

#include "sensors.h"
#include "window.h"

struct SensorMlResult {
  bool  valid;          // false: no model compiled in, or window/baseline/heaters not ready
  int   cls;            // 0 NORMAL, 1 CONTROLLED_FLAME, 2 HAZARDOUS_FIRE
  float conf;           // forest vote share of the winning class (0-1)
  float p[3];
  float anomaly;        // isolation-forest score in (0,1), higher = more anomalous
  bool  anomalous;      // anomaly > threshold chosen at training time
};

bool sensor_ml_available();
const char* sensor_ml_class_name(int cls);
const char* sensor_ml_version();

// Builds the 16 features (identical math to sensor_common.py). Exposed for the parity test.
void sensor_ml_features(const WindowStats& w, const SensorBaseline& b, float out[16]);

SensorMlResult sensor_ml_infer(const WindowStats& w, const SensorBaseline& b, unsigned long now_ms);

#endif
