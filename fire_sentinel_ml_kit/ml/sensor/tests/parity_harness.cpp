// Reads window statistics + baseline from stdin (one window per line), runs the REAL firmware inference code
// (sensor_ml.cpp + generated sensor_model.h) and prints: 16 features, 3 class probabilities, anomaly score.
#include <stdio.h>
#include "sensor_ml.h"
#include "config.h"
int main() {
  double v[6 * 3 + 5];
  while (true) {
    for (int i = 0; i < 23; i++) if (scanf("%lf", &v[i]) != 1) return 0;
    WindowStats w = {}; SensorBaseline b = {};
    w.ready = true; w.n = WINDOW_SIZE;
    for (int c = 0; c < WCH_COUNT; c++) { w.mean[c] = (float)v[c]; w.stddev[c] = (float)v[6 + c]; w.slope_per_s[c] = (float)v[12 + c]; }
    b.temp_baseline_c = (float)v[18]; b.mq2_baseline = (float)v[19]; b.mq7_baseline = (float)v[20];
    b.mq135_baseline = (float)v[21]; b.uv_baseline = (float)v[22]; b.temp_ready = b.gas_ready = true;
    float f[16]; sensor_ml_features(w, b, f);
    SensorMlResult r = sensor_ml_infer(w, b, 1000000000UL);
    for (int i = 0; i < 16; i++) printf("%.9g ", f[i]);
    printf("%.9g %.9g %.9g %.9g %d\n", r.p[0], r.p[1], r.p[2], r.anomaly, r.anomalous ? 1 : 0);
  }
}
