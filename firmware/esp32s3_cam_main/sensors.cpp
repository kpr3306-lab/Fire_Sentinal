/*
 * sensors.cpp — Fire Sentinel (v2)
 *
 * Libraries: Adafruit BME280 (+Unified Sensor), Adafruit ADS1X15.
 * MQ ppm values are still PLACEHOLDER linear maps (flagged in the payload as
 * *_est). The baseline/fusion logic works on raw ADS counts, which is also what
 * you should train the sensor classifier on.
 */

#include "sensors.h"
#include "config.h"
#include "i2c_util.h"
#include <Wire.h>
#include <Preferences.h>
#include <Adafruit_BME280.h>
#include <Adafruit_ADS1X15.h>
#include <math.h>

static Adafruit_BME280  bme;
static Adafruit_ADS1115 ads;
static bool bme_ok = false;
static bool ads_ok = false;
static uint8_t bme_addr = BME280_I2C_ADDR;
static unsigned long last_reinit_ms = 0;

static SensorBaseline bl = {};
static Preferences prefs;

// Anchors: the first "ready" baseline values. Learning is clamped around them
// so a slow smolder cannot be absorbed into "normal" indefinitely.
static bool  anchor_temp_set = false, anchor_gas_set = false;
static float anchor_temp = 0, anchor_mq2 = 0, anchor_mq7 = 0, anchor_mq135 = 0;
static bool  saved_once = false;
static unsigned long last_save_ms = 0;

// ---- flame debounce -------------------------------------------------------
static bool flame_hist[FLAME_HISTORY] = {};
static uint8_t flame_idx = 0;
static unsigned long last_flame_poll_ms = 0;

void sensors_flame_poll(unsigned long now_ms) {
  if (now_ms - last_flame_poll_ms < FLAME_POLL_INTERVAL_MS) return;
  last_flame_poll_ms = now_ms;
  int s = digitalRead(FLAME_DIGITAL_GPIO);
  flame_hist[flame_idx] = FLAME_ACTIVE_LOW ? (s == LOW) : (s == HIGH);
  flame_idx = (flame_idx + 1) % FLAME_HISTORY;
}

static bool flame_filtered() {
  int hits = 0;
  for (int i = 0; i < FLAME_HISTORY; i++) if (flame_hist[i]) hits++;
  return hits >= FLAME_MIN_HITS;
}

// ---- helpers --------------------------------------------------------------
static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

float sensors_rel_dev(float value, float baseline) {
  if (baseline < MQ_MIN_BASELINE_RAW) baseline = MQ_MIN_BASELINE_RAW;
  return (value - baseline) / baseline;
}

// Placeholder: ADS counts -> volts at the sensor pin (undo the divider) -> linear ppm.
static float counts_to_volts(int raw) { return raw * 0.125f / 1000.0f; }
static float est_mq_ppm(int raw, float max_ppm) {
  float v_aout = counts_to_volts(raw) * MQ_DIVIDER_RATIO;      // volts at the MQ AOUT pin
  return clampf(v_aout / 5.0f, 0.0f, 1.0f) * max_ppm;
}
static float est_uv_index(int raw) {                            // GUVA-S12D ~0.1 V per UV index
  return clampf(counts_to_volts(raw) / 0.1f, 0.0f, 15.0f);
}

// ---- NVS (only the gas/UV baseline is persisted; room temperature varies by day) ----
static void load_baseline() {
  prefs.begin("fsbase", true);
  bool ok = prefs.getUChar("ver", 0) == BASELINE_NVS_VERSION && prefs.getBool("gr", false);
  if (ok) {
    bl.mq2_baseline   = prefs.getFloat("m2", 0);
    bl.mq7_baseline   = prefs.getFloat("m7", 0);
    bl.mq135_baseline = prefs.getFloat("m135", 0);
    bl.uv_baseline    = prefs.getFloat("uv", 0);
    bl.gas_ready = true;
    bl.gas_samples = BASELINE_EMA_SAMPLES;
    bl.gas_loaded_from_nvs = true;
    anchor_mq2 = bl.mq2_baseline; anchor_mq7 = bl.mq7_baseline; anchor_mq135 = bl.mq135_baseline;
    anchor_gas_set = true;
  }
  prefs.end();
  if (ok) Serial.println("[sensors] Gas baseline restored from NVS (still waits for MQ heater warm-up).");
}

static void save_baseline(unsigned long now_ms) {
  prefs.begin("fsbase", false);
  prefs.putUChar("ver", BASELINE_NVS_VERSION);
  prefs.putBool("gr", true);
  prefs.putFloat("m2", bl.mq2_baseline);
  prefs.putFloat("m7", bl.mq7_baseline);
  prefs.putFloat("m135", bl.mq135_baseline);
  prefs.putFloat("uv", bl.uv_baseline);
  prefs.end();
  saved_once = true;
  last_save_ms = now_ms;
}

void sensors_clear_saved_baseline() {
  prefs.begin("fsbase", false);
  prefs.clear();
  prefs.end();
  Serial.println("[sensors] Saved baseline cleared.");
}

// ---- init -----------------------------------------------------------------
static bool try_init_bme() {
  bme_addr = BME280_I2C_ADDR;
  if (bme.begin(bme_addr)) return true;
  bme_addr = 0x77;
  return bme.begin(bme_addr);
}

// Boot diagnostic when the BME280 fails: list every I2C device and read the Bosch
// chip-ID register (0xD0) so a BMP280 sold as "BME280" (ID 0x58, no humidity) is obvious.
static void diagnose_bme() {
  Serial.print("[sensors] I2C scan:");
  for (uint8_t a = 1; a < 127; a++) if (i2c_ping(a)) Serial.printf(" 0x%02X", a);
  Serial.println();
  for (uint8_t a : {(uint8_t)0x76, (uint8_t)0x77}) {
    if (!i2c_ping(a)) continue;
    Wire.beginTransmission(a); Wire.write(0xD0); Wire.endTransmission();
    if (Wire.requestFrom(a, (uint8_t)1) != 1) continue;
    uint8_t id = Wire.read();
    Serial.printf("[sensors] 0x%02X chip ID 0x%02X: %s\n", a, id,
                  id == 0x60 ? "BME280 (wiring/power issue?)" :
                  id == 0x58 ? "BMP280 - not a BME280, no humidity; library rejects it" :
                  "unknown chip");
  }
}
static bool try_init_ads() {
  if (!ads.begin(ADS1115_I2C_ADDR)) return false;
  ads.setGain(GAIN_ONE);            // +/-4.096 V; MQ inputs are halved by the divider
  return true;
}

bool sensors_init() {
  Wire.begin(I2C_SDA_GPIO, I2C_SCL_GPIO);
  Wire.setClock(I2C_CLOCK_HZ);

#if BME280_FITTED
  bme_ok = try_init_bme();
  if (!bme_ok) { Serial.println("[sensors] ERROR: BME280 not responding (tried 0x76 and 0x77)."); diagnose_bme(); }
#else
  bl.temp_ready = true;             // no temperature sensor: temperature stays 0 and never gates readiness
#endif
  ads_ok = try_init_ads();
  if (!ads_ok) Serial.println("[sensors] ERROR: ADS1115 not responding.");

  pinMode(FLAME_DIGITAL_GPIO, INPUT);
  load_baseline();
  return (bme_ok || !BME280_FITTED) && ads_ok;
}

// ---- read -----------------------------------------------------------------
SensorReading sensors_read() {
  SensorReading r = {};
  r.timestamp_ms = millis();

  // Runtime I2C loss detection + slow re-init (no reboot needed after a loose wire)
  if (bme_ok && !i2c_ping(bme_addr)) { bme_ok = false; Serial.println("[sensors] BME280 lost."); }
  if (ads_ok && !i2c_ping(ADS1115_I2C_ADDR)) { ads_ok = false; Serial.println("[sensors] ADS1115 lost."); }
  if (((BME280_FITTED && !bme_ok) || !ads_ok) && r.timestamp_ms - last_reinit_ms >= 10000UL) {
    last_reinit_ms = r.timestamp_ms;
    if (BME280_FITTED && !bme_ok) { bme_ok = try_init_bme(); if (bme_ok) Serial.println("[sensors] BME280 recovered."); }
    if (!ads_ok) { ads_ok = try_init_ads(); if (ads_ok) Serial.println("[sensors] ADS1115 recovered."); }
  }

  if (bme_ok) {
    float t = bme.readTemperature();
    float h = bme.readHumidity();
    float p = bme.readPressure() / 100.0f;
    if (!isnan(t) && !isnan(h) && !isnan(p)) {
      r.temperature_c = t; r.humidity_pct = h; r.pressure_hpa = p;
      r.env_valid = true;
    }
  }

  if (ads_ok) {
    int a0 = ads.readADC_SingleEnded(ADS_CH_MQ2);
    int a1 = ads.readADC_SingleEnded(ADS_CH_MQ7);
    int a2 = ads.readADC_SingleEnded(ADS_CH_MQ135);
    int a3 = ads.readADC_SingleEnded(ADS_CH_UV);
    r.mq2_raw   = a0 < 0 ? 0 : a0;     // noise can read slightly negative
    r.mq7_raw   = a1 < 0 ? 0 : a1;
    r.mq135_raw = a2 < 0 ? 0 : a2;
    r.uv_raw    = a3 < 0 ? 0 : a3;
    r.mq2_ppm_est   = est_mq_ppm(r.mq2_raw, 500.0f);
    r.mq7_ppm_est   = est_mq_ppm(r.mq7_raw, 200.0f);
    r.mq135_ppm_est = est_mq_ppm(r.mq135_raw, 300.0f);
    r.uv_index_est  = est_uv_index(r.uv_raw);
    r.gas_valid = true;
  }

  r.flame_detected = flame_filtered();
  r.valid = (r.env_valid || !BME280_FITTED) && r.gas_valid;
  return r;
}

// ---- baseline -------------------------------------------------------------
static float ema(float cur, float sample, int n_after_inc) {
  int n = n_after_inc < BASELINE_EMA_SAMPLES ? n_after_inc : BASELINE_EMA_SAMPLES;
  return cur + (sample - cur) / (float)n;      // running mean at first, slow EMA later
}

void sensors_update_baseline(const SensorReading& r, unsigned long now_ms) {
  // ---- temperature group ----
  if (r.env_valid) {
    bool freeze = bl.temp_ready && fabsf(r.temperature_c - bl.temp_baseline_c) > BASELINE_FREEZE_TEMP_DEV_C;
    if (!freeze) {
      if (bl.temp_samples < BASELINE_EMA_SAMPLES) bl.temp_samples++;
      bl.temp_baseline_c = (bl.temp_samples == 1) ? r.temperature_c
                                                  : ema(bl.temp_baseline_c, r.temperature_c, bl.temp_samples);
      if (!bl.temp_ready && bl.temp_samples >= BASELINE_WARMUP_SAMPLES) {
        bl.temp_ready = true;
        anchor_temp = bl.temp_baseline_c; anchor_temp_set = true;
      }
      if (anchor_temp_set)
        bl.temp_baseline_c = clampf(bl.temp_baseline_c, anchor_temp - BASELINE_ANCHOR_TEMP_MAX_C,
                                                         anchor_temp + BASELINE_ANCHOR_TEMP_MAX_C);
    }
  }

  // ---- gas + UV group (only after MQ heaters have warmed up) ----
  if (r.gas_valid && r.timestamp_ms >= MQ_HEATER_WARMUP_MS) {
    bool freeze = false;
    if (bl.gas_ready) {
      if (sensors_rel_dev(r.mq2_raw,   bl.mq2_baseline)   > BASELINE_FREEZE_GAS_DEV ||
          sensors_rel_dev(r.mq7_raw,   bl.mq7_baseline)   > BASELINE_FREEZE_GAS_DEV ||
          sensors_rel_dev(r.mq135_raw, bl.mq135_baseline) > BASELINE_FREEZE_GAS_DEV) freeze = true;
    }
    if (!freeze) {
      bool first = (bl.gas_samples == 0);
      if (bl.gas_samples < BASELINE_EMA_SAMPLES) bl.gas_samples++;
      if (first) {
        bl.mq2_baseline = r.mq2_raw; bl.mq7_baseline = r.mq7_raw;
        bl.mq135_baseline = r.mq135_raw; bl.uv_baseline = r.uv_raw;
      } else {
        bl.mq2_baseline   = ema(bl.mq2_baseline,   r.mq2_raw,   bl.gas_samples);
        bl.mq7_baseline   = ema(bl.mq7_baseline,   r.mq7_raw,   bl.gas_samples);
        bl.mq135_baseline = ema(bl.mq135_baseline, r.mq135_raw, bl.gas_samples);
        bl.uv_baseline    = ema(bl.uv_baseline,    r.uv_raw,    bl.gas_samples);
      }
      if (!bl.gas_ready && bl.gas_samples >= BASELINE_WARMUP_SAMPLES) {
        bl.gas_ready = true;
        anchor_mq2 = bl.mq2_baseline; anchor_mq7 = bl.mq7_baseline; anchor_mq135 = bl.mq135_baseline;
        anchor_gas_set = true;
      }
      if (anchor_gas_set) {
        bl.mq2_baseline   = clampf(bl.mq2_baseline,   anchor_mq2   * BASELINE_ANCHOR_GAS_MIN_RATIO, anchor_mq2   * BASELINE_ANCHOR_GAS_MAX_RATIO);
        bl.mq7_baseline   = clampf(bl.mq7_baseline,   anchor_mq7   * BASELINE_ANCHOR_GAS_MIN_RATIO, anchor_mq7   * BASELINE_ANCHOR_GAS_MAX_RATIO);
        bl.mq135_baseline = clampf(bl.mq135_baseline, anchor_mq135 * BASELINE_ANCHOR_GAS_MIN_RATIO, anchor_mq135 * BASELINE_ANCHOR_GAS_MAX_RATIO);
      }
      if (bl.gas_ready && (!saved_once || now_ms - last_save_ms >= BASELINE_SAVE_INTERVAL_MS)) {
        save_baseline(now_ms);
      }
    }
  }
}

SensorBaseline sensors_get_baseline() { return bl; }
