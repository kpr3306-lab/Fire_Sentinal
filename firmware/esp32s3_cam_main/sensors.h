/*
 * sensors.h — Ignis (v2)
 * BME280 + ADS1115 (MQ-2/MQ-7/MQ-135/UV) + debounced B35 flame input, plus the
 * self-protecting baseline (calibration) that the fusion layer compares against.
 */
#ifndef SENSORS_H
#define SENSORS_H

#include <Arduino.h>

struct SensorReading {
  float temperature_c;
  float humidity_pct;
  float pressure_hpa;

  int   mq2_raw;        // ADS1115 counts (0.125 mV/count at GAIN_ONE), after the 10k/10k divider
  int   mq7_raw;
  int   mq135_raw;
  int   uv_raw;

  float mq2_ppm_est;    // PLACEHOLDER linear estimates — train/analyse on *_raw instead
  float mq7_ppm_est;
  float mq135_ppm_est;
  float uv_index_est;

  bool  flame_detected; // debounced (>= FLAME_MIN_HITS of last FLAME_HISTORY polls)
  unsigned long timestamp_ms;

  bool  env_valid;      // BME280 read OK this cycle
  bool  gas_valid;      // ADS1115 read OK this cycle
  bool  valid;          // env_valid && gas_valid
};

struct SensorBaseline {
  float temp_baseline_c;
  float mq2_baseline;   // raw ADS counts
  float mq7_baseline;
  float mq135_baseline;
  float uv_baseline;
  int   temp_samples;
  int   gas_samples;
  bool  temp_ready;
  bool  gas_ready;
  bool  gas_loaded_from_nvs;
};

bool sensors_init();                        // false if BME280 or ADS1115 missing (device keeps running)
void sensors_flame_poll(unsigned long now_ms);   // call every loop pass; self-rate-limits to 100 ms
SensorReading sensors_read();               // ~40 ms (4 ADS conversions); detects runtime I2C loss

// Feed a reading into the baseline. Call ONLY while the state machine is NORMAL.
// Learning self-freezes when readings drift away from baseline, and the baseline
// can never creep more than a bounded distance from its anchor (slow-fire protection).
void sensors_update_baseline(const SensorReading& reading, unsigned long now_ms);
SensorBaseline sensors_get_baseline();
void sensors_clear_saved_baseline();        // wipes the NVS copy (hold info button at boot)

// (value - baseline) / baseline with a floor on baseline.
float sensors_rel_dev(float value, float baseline);

#endif
