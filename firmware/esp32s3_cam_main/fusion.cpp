/*
 * fusion.cpp — Fire Sentinel Prototype 2 (v2)
 *
 * Weights (see config.h): flame 35, UV 10, temperature 25, gas 30, multi-gas
 * agreement 10  => 110 clamped to 100. Without flame the maximum is 75, so a
 * smoldering fire can reach CONFIRMING (50) and FIRE (65).
 *
 * Temperature points = max(baseline deviation, rate of rise, absolute level).
 * An absolute reading >= 57 C floors the score at CONFIRMING regardless of
 * baseline (fixed-temperature heat detector behaviour) — the safety net that
 * a drifting baseline cannot defeat.
 *
 * Weights/thresholds are placeholders to be re-derived from the trained
 * classifier's feature importances once trial data exists.
 */

#include "fusion.h"
#include "config.h"
#include <math.h>

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
static float maxf(float a, float b) { return a > b ? a : b; }

FusionResult fusion_compute(const SensorReading& r, const SensorBaseline& b, const WindowStats& w) {
  FusionResult f = {};
  f.flame_signal = r.flame_detected;
  f.sensor_fault = !r.valid;

  float score = 0;
  bool temp_alarm = false;

  // --- Flame ---
  if (r.flame_detected) score += FUSION_W_FLAME;

  // --- Temperature ---
  if (r.env_valid) {
    float pts = 0;
    if (b.temp_ready) {
      f.temp_deviation = r.temperature_c - b.temp_baseline_c;
      pts = maxf(pts, clampf(f.temp_deviation / TEMP_FULL_DEV_C, 0, 1) * FUSION_W_TEMP);
    }
    if (w.ready) {
      f.temp_rate_c_per_min = w.slope_per_s[WCH_TEMP] * 60.0f;
      pts = maxf(pts, clampf(f.temp_rate_c_per_min / TEMP_RATE_FULL_C_PER_MIN, 0, 1) * FUSION_W_TEMP);
    }
    if (r.temperature_c >= TEMP_ABS_ALARM_C) { pts = FUSION_W_TEMP; temp_alarm = true; }
    else if (r.temperature_c >= TEMP_ABS_ELEVATED_C) pts = maxf(pts, FUSION_W_TEMP * 0.4f);
    score += pts;
  }

  // --- Gas + UV ---
  bool heaters_warm = r.timestamp_ms >= MQ_HEATER_WARMUP_MS;
  if (r.gas_valid && b.gas_ready && heaters_warm) {
    f.gas_terms_active = true;
    float d2   = sensors_rel_dev(r.mq2_raw,   b.mq2_baseline);
    float d7   = sensors_rel_dev(r.mq7_raw,   b.mq7_baseline);
    float d135 = sensors_rel_dev(r.mq135_raw, b.mq135_baseline);
    float worst = maxf(d2, maxf(d7, d135));
    f.gas_deviation_pct = worst * 100.0f;
    score += clampf(worst / GAS_FULL_DEV, 0, 1) * FUSION_W_GAS;

    f.gas_agree_count = (d2 >= GAS_AGREE_DEV) + (d7 >= GAS_AGREE_DEV) + (d135 >= GAS_AGREE_DEV);
    if (f.gas_agree_count >= 2) score += FUSION_W_GAS_AGREE;

    float uv_counts = r.uv_raw - b.uv_baseline;
    score += clampf(uv_counts / UV_FULL_SCALE_COUNTS, 0, 1) * FUSION_W_UV;
  } else if (r.gas_valid) {
    // Warm-up / no baseline yet: coarse absolute fallback only
    if (r.mq2_raw > MQ2_ABS_ALARM_RAW || r.mq7_raw > MQ7_ABS_ALARM_RAW) score += 10;
  }

  int s = (int)clampf(score, 0, 100);
  if (temp_alarm && s < RISK_THRESHOLD_CONFIRMING) s = RISK_THRESHOLD_CONFIRMING;
  f.risk_score = s;
  return f;
}
