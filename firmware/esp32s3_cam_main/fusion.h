/*
 * fusion.h — rule-based on-device risk score (0-100), transparent and auditable.
 * Runs standalone even if the backend is unreachable.
 */
#ifndef FUSION_H
#define FUSION_H

#include "sensors.h"
#include "window.h"

struct FusionResult {
  int   risk_score;          // 0-100
  float temp_deviation;      // C above baseline (0 if baseline not ready)
  float temp_rate_c_per_min; // from the 30 s window (0 if window not ready)
  float gas_deviation_pct;   // worst of 3 MQ vs baseline, % (0 if gas terms inactive)
  int   gas_agree_count;     // how many MQ sensors are > +40%
  bool  gas_terms_active;    // false while heaters warm up / baseline learning
  bool  flame_signal;        // debounced
  bool  sensor_fault;        // a sensor group is not reading
};

FusionResult fusion_compute(const SensorReading& r, const SensorBaseline& b, const WindowStats& w);

#endif
