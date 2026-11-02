#include "sensor_ml.h"
#include "config.h"
#include "sensor_model.h"
#include <math.h>

bool sensor_ml_available() { return SENSOR_MODEL_PRESENT; }
const char* sensor_ml_version() { return SENSOR_MODEL_VERSION; }

const char* sensor_ml_class_name(int cls) {
  static const char* const names[3] = {"NORMAL", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"};
  return (cls >= 0 && cls < 3) ? names[cls] : "UNKNOWN";
}

void sensor_ml_features(const WindowStats& w, const SensorBaseline& b, float f[16]) {
  const float UVN = UV_FULL_SCALE_COUNTS;
  f[0] = w.mean[WCH_TEMP] - b.temp_baseline_c;
  f[1] = w.stddev[WCH_TEMP];
  f[2] = w.slope_per_s[WCH_TEMP] * 60.0f;

  const int   ch[3]   = {WCH_MQ2, WCH_MQ7, WCH_MQ135};
  const float base[3] = {b.mq2_baseline, b.mq7_baseline, b.mq135_baseline};
  for (int k = 0; k < 3; k++) {
    float bb = base[k] < MQ_MIN_BASELINE_RAW ? MQ_MIN_BASELINE_RAW : base[k];
    f[3 + 3 * k] = w.mean[ch[k]] / bb - 1.0f;
    f[4 + 3 * k] = w.stddev[ch[k]] / bb;
    f[5 + 3 * k] = w.slope_per_s[ch[k]] * 60.0f / bb;
  }
  f[12] = (w.mean[WCH_UV] - b.uv_baseline) / UVN;
  f[13] = w.stddev[WCH_UV] / UVN;
  f[14] = w.slope_per_s[WCH_UV] * 60.0f / UVN;
  f[15] = w.mean[WCH_FLAME];
}

#if SENSOR_MODEL_PRESENT
static int walk(const int8_t* feat, const float* thr, const int16_t* left, const int16_t* right,
                int root, const float* x) {
  int n = root;
  while (feat[n] >= 0) n = (x[feat[n]] <= thr[n]) ? left[n] : right[n];
  return n;                                           // leaf node index
}
#endif

SensorMlResult sensor_ml_infer(const WindowStats& w, const SensorBaseline& b, unsigned long now_ms) {
  SensorMlResult r = {};
#if SENSOR_MODEL_PRESENT
  if (!w.ready || !b.temp_ready || !b.gas_ready || now_ms < MQ_HEATER_WARMUP_MS) return r;

  float x[SENSOR_N_FEATURES];
  sensor_ml_features(w, b, x);

  float acc[3] = {0, 0, 0};
  for (int t = 0; t < SENSOR_RF_N_TREES; t++) {
    int leaf = walk(SENSOR_RF_FEAT, SENSOR_RF_THR, SENSOR_RF_LEFT, SENSOR_RF_RIGHT, SENSOR_RF_ROOT[t], x);
    const uint8_t* p = SENSOR_RF_LEAF[SENSOR_RF_LEFT[leaf]];
    for (int c = 0; c < 3; c++) acc[c] += p[c] / 255.0f;
  }
  int best = 0;
  for (int c = 0; c < 3; c++) { r.p[c] = acc[c] / SENSOR_RF_N_TREES; if (r.p[c] > r.p[best]) best = c; }
  r.cls = best;
  r.conf = r.p[best];

  float sum_h = 0;
  for (int t = 0; t < SENSOR_IF_N_TREES; t++)
    sum_h += SENSOR_IF_THR[walk(SENSOR_IF_FEAT, SENSOR_IF_THR, SENSOR_IF_LEFT, SENSOR_IF_RIGHT, SENSOR_IF_ROOT[t], x)];
  r.anomaly = powf(2.0f, -(sum_h / SENSOR_IF_N_TREES) / SENSOR_IF_C);
  r.anomalous = r.anomaly > SENSOR_IF_THRESHOLD;
  r.valid = true;
#else
  (void)w; (void)b; (void)now_ms;
#endif
  return r;
}
