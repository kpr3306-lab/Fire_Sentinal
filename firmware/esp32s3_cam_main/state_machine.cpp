#include "state_machine.h"
#include "config.h"

static FireState state = FireState::NORMAL;
static unsigned long state_entered_ms = 0;
static unsigned long confirming_streak_start_ms = 0;
static bool confirming_streak_active = false;
static unsigned long below_precursor_since_ms = 0;
static bool below_precursor_active = false;

static void enter_state(FireState s, unsigned long now_ms) {
  state = s;
  state_entered_ms = now_ms;
  confirming_streak_active = false;
  below_precursor_active = false;
}

FireState state_machine_get_state() { return state; }

StateMachineOutput state_machine_update(const FusionResult& fusion, unsigned long now_ms) {
  StateMachineOutput out = {};
  FireState previous = state;
  const int score = fusion.risk_score;
  const bool flame = fusion.flame_signal;

  switch (state) {
    case FireState::NORMAL:
      if (flame || score >= RISK_THRESHOLD_PRECURSOR) {
        enter_state(FireState::PRECURSOR, now_ms);
        out.camera_trigger_requested = true;
      }
      break;

    case FireState::PRECURSOR:
      if (flame || score >= RISK_THRESHOLD_CONFIRMING) {
        enter_state(FireState::CONFIRMING, now_ms);
        confirming_streak_active = true;
        confirming_streak_start_ms = now_ms;
        out.camera_trigger_requested = true;
      } else if (score < RISK_THRESHOLD_PRECURSOR) {
        if (!below_precursor_active) {
          below_precursor_active = true;
          below_precursor_since_ms = now_ms;
        } else if (now_ms - below_precursor_since_ms >= PRECURSOR_COOLDOWN_MS) {
          enter_state(FireState::NORMAL, now_ms);
        }
      } else {
        below_precursor_active = false;
      }
      break;

    case FireState::CONFIRMING: {
      const bool high_evidence = flame || (score >= RISK_THRESHOLD_CONFIRMING);
      if (!high_evidence) { enter_state(FireState::PRECURSOR, now_ms); break; }

      if (!confirming_streak_active) {
        confirming_streak_active = true;
        confirming_streak_start_ms = now_ms;
      }
      // Fire-level: strong score on its own, OR flame corroborated by other signals.
      const bool fire_level = (score >= RISK_THRESHOLD_FIRE) ||
                              (flame && score >= RISK_THRESHOLD_CONFIRMING);
      if (fire_level && (now_ms - confirming_streak_start_ms) >= SUSTAINED_CONFIRM_WINDOW_MS) {
        enter_state(FireState::FIRE_CONFIRMED, now_ms);
        out.camera_trigger_requested = true;
      }
      break;
    }

    case FireState::FIRE_CONFIRMED: {
      const bool still_elevated = flame || (score >= RISK_THRESHOLD_CONFIRMING);
      if ((now_ms - state_entered_ms) >= FIRE_HOLD_MS && !still_elevated) {
        enter_state(FireState::CONFIRMING, now_ms);
      }
      break;
    }
  }

  out.state_changed_this_cycle = (state != previous);
  out.current_state = state;
  out.should_upload_to_backend = out.state_changed_this_cycle || (state != FireState::NORMAL);
  return out;
}

const char* state_machine_state_name(FireState s) {
  switch (s) {
    case FireState::NORMAL:         return "NORMAL";
    case FireState::PRECURSOR:      return "PRECURSOR";
    case FireState::CONFIRMING:     return "CONFIRMING";
    case FireState::FIRE_CONFIRMED: return "FIRE_CONFIRMED";
  }
  return "UNKNOWN";
}
