/*
 * buzzer.h — non-blocking alert patterns on GPIO42.
 *   PRECURSOR      : one short beep every 6 s
 *   CONFIRMING     : double beep every 1.5 s
 *   FIRE_CONFIRMED : continuous tone
 * Silencing affects the BUZZER ONLY (never state or backend alerts) and
 * re-arms automatically when severity increases, the state returns to NORMAL,
 * or the silence period ends (60 s during FIRE_CONFIRMED).
 */
#ifndef BUZZER_H
#define BUZZER_H

#include <Arduino.h>
#include "state_machine.h"

void buzzer_init();
void buzzer_boot_chirp();                              // blocking ~150 ms, setup() only
void buzzer_set_state(FireState s, unsigned long now_ms);
void buzzer_silence(unsigned long now_ms);
bool buzzer_is_silenced(unsigned long now_ms);
void buzzer_tick(unsigned long now_ms);

#endif
