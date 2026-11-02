#include "buzzer.h"
#include "config.h"

static FireState cur = FireState::NORMAL;
static unsigned long pattern_start_ms = 0;
static unsigned long silenced_until_ms = 0;
static bool silenced = false;
static bool sounding = false;
static int  sounding_freq = 0;

// ---- hardware layer (core 2.x and 3.x LEDC APIs) --------------------------
static void hw_init() {
#if BUZZER_PASSIVE
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttachChannel(BUZZER_GPIO, 2000, 8, BUZZER_LEDC_CHANNEL);
    ledcWriteTone(BUZZER_GPIO, 0);
  #else
    ledcSetup(BUZZER_LEDC_CHANNEL, 2000, 8);
    ledcAttachPin(BUZZER_GPIO, BUZZER_LEDC_CHANNEL);
    ledcWriteTone(BUZZER_LEDC_CHANNEL, 0);
  #endif
#else
  pinMode(BUZZER_GPIO, OUTPUT);
  digitalWrite(BUZZER_GPIO, LOW);
#endif
}

static void hw_tone(int freq_hz) {              // 0 = off
#if BUZZER_PASSIVE
  #if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWriteTone(BUZZER_GPIO, freq_hz);
  #else
    ledcWriteTone(BUZZER_LEDC_CHANNEL, freq_hz);
  #endif
#else
  digitalWrite(BUZZER_GPIO, freq_hz > 0 ? HIGH : LOW);
#endif
}

static void apply(bool on, int freq) {
  if (on == sounding && (!on || freq == sounding_freq)) return;   // only touch hardware on change
  sounding = on; sounding_freq = on ? freq : 0;
  hw_tone(sounding_freq);
}

void buzzer_init() { hw_init(); }

void buzzer_boot_chirp() {
  hw_tone(BUZZER_FREQ_PRECURSOR_HZ); delay(80);
  hw_tone(0);                         delay(50);
  hw_tone(BUZZER_FREQ_CONFIRMING_HZ); delay(80);
  hw_tone(0);
}

static unsigned long silence_duration(FireState s) {
  return (s == FireState::FIRE_CONFIRMED) ? BUZZER_SILENCE_FIRE_MS : BUZZER_SILENCE_MS;
}

void buzzer_set_state(FireState s, unsigned long now_ms) {
  if (s == cur) return;
  if (s == FireState::NORMAL || (int)s > (int)cur) silenced = false;    // re-arm on escalation / clear
  cur = s;
  pattern_start_ms = now_ms;
}

void buzzer_silence(unsigned long now_ms) {
  if (cur == FireState::NORMAL) return;
  silenced = true;
  silenced_until_ms = now_ms + silence_duration(cur);
  apply(false, 0);
}

bool buzzer_is_silenced(unsigned long now_ms) {
  if (silenced && (long)(silenced_until_ms - now_ms) <= 0) silenced = false;
  return silenced;
}

void buzzer_tick(unsigned long now_ms) {
  if (cur == FireState::NORMAL || buzzer_is_silenced(now_ms)) { apply(false, 0); return; }

  unsigned long phase;
  switch (cur) {
    case FireState::PRECURSOR:
      phase = (now_ms - pattern_start_ms) % 6000UL;
      apply(phase < 120, BUZZER_FREQ_PRECURSOR_HZ);
      break;
    case FireState::CONFIRMING:
      phase = (now_ms - pattern_start_ms) % 1500UL;
      apply(phase < 100 || (phase >= 200 && phase < 300), BUZZER_FREQ_CONFIRMING_HZ);
      break;
    case FireState::FIRE_CONFIRMED:
      apply(true, BUZZER_FREQ_FIRE_HZ);
      break;
    default:
      apply(false, 0);
  }
}
