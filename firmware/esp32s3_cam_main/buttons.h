/*
 * buttons.h — single info button (GPIO2, INPUT_PULLUP, other leg to GND).
 *   short press : next OLED screen
 *   long press  : silence the buzzer (acknowledge)
 *   hold at boot: clear the saved gas baseline
 */
#ifndef BUTTONS_H
#define BUTTONS_H

#include <Arduino.h>

enum class ButtonEvent { NONE, SHORT_PRESS, LONG_PRESS };

void buttons_init();
ButtonEvent buttons_poll(unsigned long now_ms);       // non-blocking, debounced
bool buttons_held_at_boot(unsigned long hold_ms);     // blocking up to hold_ms, setup() only
#endif
