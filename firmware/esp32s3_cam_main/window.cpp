#include "window.h"
#include "config.h"
#include <math.h>

const char* const WINDOW_CHANNEL_NAMES[WCH_COUNT] = {"temp", "mq2", "mq7", "mq135", "uv", "flame"};

static float buf[WCH_COUNT][WINDOW_SIZE];
static int head = 0, count = 0;

void window_push(const SensorReading& r) {
  buf[WCH_TEMP][head]  = r.temperature_c;
  buf[WCH_MQ2][head]   = (float)r.mq2_raw;
  buf[WCH_MQ7][head]   = (float)r.mq7_raw;
  buf[WCH_MQ135][head] = (float)r.mq135_raw;
  buf[WCH_UV][head]    = (float)r.uv_raw;
  buf[WCH_FLAME][head] = r.flame_detected ? 1.0f : 0.0f;
  head = (head + 1) % WINDOW_SIZE;
  if (count < WINDOW_SIZE) count++;
}

void window_reset() { head = 0; count = 0; }

WindowStats window_compute() {
  WindowStats s = {};
  s.n = count;
  s.ready = (count >= WINDOW_SIZE);
  if (count < 2) return s;

  const float dt_s = SENSOR_SAMPLE_INTERVAL_MS / 1000.0f;
  const int start = (head - count + WINDOW_SIZE) % WINDOW_SIZE;
  const float n = (float)count;
  const float sx  = n * (n - 1) / 2.0f;
  const float sxx = (n - 1) * n * (2 * n - 1) / 6.0f;
  const float denom = n * sxx - sx * sx;

  for (int c = 0; c < WCH_COUNT; c++) {
    float sum = 0, sxy = 0;
    for (int i = 0; i < count; i++) {
      float y = buf[c][(start + i) % WINDOW_SIZE];
      sum += y; sxy += (float)i * y;
    }
    float mean = sum / n;
    float var = 0;
    for (int i = 0; i < count; i++) {
      float d = buf[c][(start + i) % WINDOW_SIZE] - mean;
      var += d * d;
    }
    s.mean[c] = mean;
    s.stddev[c] = sqrtf(var / n);
    s.slope_per_s[c] = (denom > 0) ? ((n * sxy - sx * sum) / denom) / dt_s : 0.0f;
  }
  return s;
}
