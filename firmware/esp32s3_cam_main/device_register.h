/*
 * device_register.h — announces device_id + IP + port to the backend. The announce
 * itself runs inside the network task; nothing here blocks the main loop.
 * device_id comes from the factory MAC (readable before WiFi starts).
 */
#ifndef DEVICE_REGISTER_H
#define DEVICE_REGISTER_H

#include <Arduino.h>

void device_register_init();                 // derive device_id (no network I/O)
const char* device_get_id();
void device_register_force();                // announce ASAP (WiFi just (re)connected)
void device_register_tick(unsigned long now_ms);   // called from the network task only

#endif
