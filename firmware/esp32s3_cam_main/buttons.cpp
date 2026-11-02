#include "buttons.h"
#include "config.h"

static bool stable_pressed = false;
static bool last_raw = false;
static unsigned long last_change_ms = 0;
static unsigned long pressed_since_ms = 0;
static bool long_fired = false;

static bool raw_pressed() { return digitalRead(INFO_BUTTON_GPIO) == LOW; }

void buttons_init() { pinMode(INFO_BUTTON_GPIO, INPUT_PULLUP); }

bool buttons_held_at_boot(unsigned long hold_ms) {
  if (!raw_pressed()) return false;
  unsigned long start = millis();
  while (raw_pressed()) {
    if (millis() - start >= hold_ms) return true;
    delay(10);
  }
  return false;
}

ButtonEvent buttons_poll(unsigned long now_ms) {
  bool raw = raw_pressed();
  if (raw != last_raw) { last_raw = raw; last_change_ms = now_ms; }

  if ((now_ms - last_change_ms) >= BUTTON_DEBOUNCE_MS && raw != stable_pressed) {
    stable_pressed = raw;
    if (stable_pressed) {
      pressed_since_ms = now_ms;
      long_fired = false;
    } else if (!long_fired) {
      return ButtonEvent::SHORT_PRESS;               // released before the long-press threshold
    }
  }
  if (stable_pressed && !long_fired && (now_ms - pressed_since_ms) >= BUTTON_LONG_PRESS_MS) {
    long_fired = true;
    return ButtonEvent::LONG_PRESS;                  // fires while still held, once
  }
  return ButtonEvent::NONE;
}
