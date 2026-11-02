/*
 * network_client.h — ALL WiFi and HTTP work lives in one FreeRTOS task (core 0).
 * The main loop only pushes small jobs into a queue and never waits on the network,
 * so sensors, state machine, buzzer, OLED and buttons keep running through WiFi
 * loss or a dead backend.
 */
#ifndef NETWORK_CLIENT_H
#define NETWORK_CLIENT_H

#include <Arduino.h>
#include "sensors.h"
#include "window.h"
#include "fusion.h"
#include "state_machine.h"
#include "sensor_ml.h"
#include "vision.h"

void network_init();                          // starts WiFi (non-blocking) + the network task
bool network_is_connected();
bool network_backend_ok();                    // a POST/announce succeeded in the last 90 s
void network_note_backend_ok();               // used by device_register

// Queue a sensor+fusion+state upload. `important` (state changes) evicts the oldest
// queued job if the queue is full. Returns false if dropped. Never blocks.
bool network_enqueue_sensor(const SensorReading& r, const FusionResult& f, FireState s,
                            const WindowStats& w,
                            bool buzzer_silenced, uint32_t ack_seq,
                            const SensorMlResult& ml, bool important);

// Queue a camera snapshot upload (capture + POST happen in the network task).
bool network_request_snapshot(const char* reason, bool fresh_frame);

// Queue an already-captured JPEG (PSRAM, from the vision task) with its on-device CNN/YOLO result.
// On success the queue owns `jpeg` and frees it; on false the caller still owns it.
bool network_enqueue_snapshot_jpeg(const char* reason, uint8_t* jpeg, size_t len, const VisionResult& vis);

#endif
