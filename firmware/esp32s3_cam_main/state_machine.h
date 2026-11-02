/*
 * state_machine.h — NORMAL -> PRECURSOR -> CONFIRMING -> FIRE_CONFIRMED
 *
 * FIRE_CONFIRMED requires (after the ~8 s sustained window) either a fire-level
 * score (>= RISK_THRESHOLD_FIRE, reachable WITHOUT flame for smolder) or
 * flame PLUS corroborating evidence (score >= CONFIRMING). A flame signal on its
 * own (sunlight, a lamp) therefore holds at CONFIRMING (Telegram + Email) but
 * never escalates to FIRE_CONFIRMED by itself.
 */
#ifndef STATE_MACHINE_H
#define STATE_MACHINE_H

#include <Arduino.h>
#include "fusion.h"

enum class FireState { NORMAL = 0, PRECURSOR = 1, CONFIRMING = 2, FIRE_CONFIRMED = 3 };

struct StateMachineOutput {
  FireState current_state;
  bool state_changed_this_cycle;
  bool camera_trigger_requested;
  bool should_upload_to_backend;
};

StateMachineOutput state_machine_update(const FusionResult& fusion, unsigned long now_ms);
const char* state_machine_state_name(FireState s);
FireState state_machine_get_state();

#endif
