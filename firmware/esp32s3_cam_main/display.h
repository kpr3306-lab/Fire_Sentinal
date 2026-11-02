/*
 * display.h — SSD1306 128x64 status screens (0x3C, shared I2C bus).
 * Info button short press cycles: STATUS -> SENSORS -> VISION -> NETWORK.
 * Screen sleeps after DISPLAY_SLEEP_MS in NORMAL; any elevated state wakes it
 * and pins it to the STATUS screen.
 */
#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>
#include "state_machine.h"

struct UiSnapshot {
  FireState state;
  int   risk;
  bool  flame;
  bool  sensor_fault;
  float temp_c, hum_pct, pres_hpa;
  int   mq2_raw, mq7_raw, mq135_raw, uv_raw;
  bool  buzzer_silenced;
  bool  ack_recent;         // long-press acknowledged in the last 5 s
};

bool display_init();
void display_splash(const char* line1, const char* line2);   // blocking ~1 s, setup() only
void display_next_screen(unsigned long now_ms);              // also wakes the screen
void display_wake(unsigned long now_ms);
void display_tick(unsigned long now_ms, const UiSnapshot& ui);

#endif
