#ifndef I2C_UTIL_H
#define I2C_UTIL_H
#include <Arduino.h>
#include <Wire.h>

// True if a device ACKs at this address. ~0.2 ms; used each cycle so a
// disconnected sensor is detected at runtime, not just at boot.
inline bool i2c_ping(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}
#endif
