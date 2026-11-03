/*
 * vision.cpp — Fire Sentinel
 *
 * Preprocessing matches training (ml/cnn/cnn_common.py, ultralytics export):
 *   JPEG (SVGA) -> esp_jpeg decode at 1/4 scale (RGB888) ->
 *   CNN : 'area' resize, squashed to 96x96               -> int8 = pixel - 128 (rescaling is inside the model)
 *   YOLO: 'area' resize into a 160x160 letterbox (pad 114) -> int8 = pixel - 128 (model scale 1/255, zp -128)
 * YOLO output [1,5,N] = cx,cy,w,h (0-1 of the 160 input), score.
 */
#include "vision.h"
#include "camera.h"
#include "network_client.h"
#include <SD_MMC.h>
#include <math.h>
#include "esp_heap_caps.h"
#include "jpeg_decoder.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "esp_system.h"
#include "esp_attr.h"
#include "esp_core_dump.h"
#include "esp_memory_utils.h"

static QueueHandle_t req_q = nullptr;
static volatile bool ready = false;
static const char* status_txt = "starting";
static VisionResult latest = {};
static portMUX_TYPE latest_mux = portMUX_INITIALIZER_UNLOCKED;

// lo/hi: guard zones around the arena. A core dump showed the CNN's allocator object (top of its arena, right
// below the YOLO arena) overwritten mid-Invoke; the guards keep a stray write out of the neighbour and report it.
struct Net { tflite::MicroInterpreter* it; uint8_t* lo; uint8_t* hi; };
static Net cnn = {}, yolo = {};
static const size_t ARENA_GUARD = 16 * 1024;
static const uint8_t GUARD_BYTE = 0xA5;

static bool guard_intact(const uint8_t* g) {
  for (size_t i = 0; i < ARENA_GUARD; i++) if (g[i] != GUARD_BYTE) return false;
  return true;
}

static void check_guards(const char* when) {
  const Net* nets[2] = {&cnn, &yolo};
  const char* names[2] = {"CNN", "YOLO"};
  for (int i = 0; i < 2; i++) {
    uint8_t* zones[2] = {nets[i]->lo, nets[i]->hi};
    for (int z = 0; z < 2; z++) {
      if (zones[z] == nullptr || guard_intact(zones[z])) continue;
      Serial.printf("[vision] guard %s the %s arena was overwritten (seen %s) — restored.\n",
                    z ? "above" : "below", names[i], when);
      memset(zones[z], GUARD_BYTE, ARENA_GUARD);
    }
  }
}

// Survives the reset after a crash (not a power cycle): which model was loading/running when the board died, so a
// model the interpreter cannot handle switches itself off instead of boot-looping the fire alarm.
// shortcut: a power cycle forgets it, so a bad model costs one reset per power-up; persist in NVS if that happens.
RTC_NOINIT_ATTR static uint32_t active_model;
static const uint32_t ACTIVE_CNN = 0x5EC0C001, ACTIVE_YOLO = 0x5EC0C002;

// Which layer ran last, kept across the reset: the crash surfaces right after the guilty layer's invoke returns.
RTC_NOINIT_ATTR static const char* last_op_tag;
RTC_NOINIT_ATTR static uint32_t last_op_idx;
struct OpTracker : tflite::MicroProfilerInterface {
  uint32_t BeginEvent(const char* tag) override { last_op_tag = tag; last_op_idx++; return 0; }
  void EndEvent(uint32_t) override {}
};
static OpTracker op_tracker;

// The flag is set while loop() and the WiFi/HTTP tasks keep running, so a panic in any of them was blamed on the
// model. The flash core dump names the task that crashed: print it, and only blame a model when it was this task.
static bool vision_task_panicked() {
  esp_core_dump_summary_t s;
  if (esp_core_dump_get_summary(&s) != ESP_OK) return true;        // no readable dump: stay cautious
  Serial.printf("[vision] last panic: task '%s' pc 0x%08lx cause %lu addr 0x%08lx | backtrace:", s.exc_task,
                (unsigned long)s.exc_pc, (unsigned long)s.ex_info.exc_cause, (unsigned long)s.ex_info.exc_vaddr);
  for (uint32_t i = 0; i < s.exc_bt_info.depth; i++) Serial.printf(" 0x%08lx", (unsigned long)s.exc_bt_info.bt[i]);
  Serial.println(s.exc_bt_info.corrupted ? " (corrupted)" : "");
  Serial.printf("[vision] last layer started: #%lu %s\n", (unsigned long)last_op_idx,
                esp_ptr_in_drom(last_op_tag) ? last_op_tag : "(name unavailable)");
  return strcmp(s.exc_task, "vision") == 0;
}

// ---------------------------------------------------------------------------
// FULLY_CONNECTED for YOLO. Its attention block multiplies two activations, so the "weights" have a non-zero zero
// point, which the built-in kernel asserts against (abort() in CalculateOpDataFullyConnected). Plain int8 math.
// ---------------------------------------------------------------------------
struct FcData { int32_t mult; int shift; int32_t act_min, act_max, in_zp, w_zp, out_zp; };

static void* fc_init(TfLiteContext* ctx, const char*, size_t) { return ctx->AllocatePersistentBuffer(ctx, sizeof(FcData)); }

static TfLiteStatus fc_prepare(TfLiteContext* ctx, TfLiteNode* node) {
  auto* d = (FcData*)node->user_data;
  tflite::MicroContext* mc = tflite::GetMicroContext(ctx);
  TfLiteTensor* in = mc->AllocateTempInputTensor(node, 0);
  TfLiteTensor* w = mc->AllocateTempInputTensor(node, 1);
  TfLiteTensor* out = mc->AllocateTempOutputTensor(node, 0);
  TfLiteStatus s = kTfLiteError;
  bool per_tensor = w && w->quantization.type == kTfLiteAffineQuantization && w->quantization.params &&
                    ((TfLiteAffineQuantization*)w->quantization.params)->scale->size == 1;
  if (in && out && per_tensor && in->type == kTfLiteInt8 && w->type == kTfLiteInt8 && out->type == kTfLiteInt8) {
    tflite::QuantizeMultiplier((double)in->params.scale * w->params.scale / out->params.scale, &d->mult, &d->shift);
    d->in_zp = in->params.zero_point; d->w_zp = w->params.zero_point; d->out_zp = out->params.zero_point;
    s = tflite::CalculateActivationRangeQuantized(ctx, ((TfLiteFullyConnectedParams*)node->builtin_data)->activation,
                                                  out, &d->act_min, &d->act_max);
  } else {
    MicroPrintf("vision FC: only int8 per-tensor supported");
  }
  if (in) mc->DeallocateTempTfLiteTensor(in);
  if (w) mc->DeallocateTempTfLiteTensor(w);
  if (out) mc->DeallocateTempTfLiteTensor(out);
  return s;
}

static TfLiteStatus fc_eval(TfLiteContext* ctx, TfLiteNode* node) {
  const auto* d = (const FcData*)node->user_data;
  const TfLiteEvalTensor* in = tflite::micro::GetEvalInput(ctx, node, 0);
  const TfLiteEvalTensor* w = tflite::micro::GetEvalInput(ctx, node, 1);
  const TfLiteEvalTensor* b = node->inputs->size > 2 ? tflite::micro::GetEvalInput(ctx, node, 2) : nullptr;
  TfLiteEvalTensor* out = tflite::micro::GetEvalOutput(ctx, node, 0);
  const int depth = w->dims->data[w->dims->size - 1], units = w->dims->data[0];
  int in_size = 1;
  for (int i = 0; i < in->dims->size; i++) in_size *= in->dims->data[i];
  const int8_t* x = in->data.int8;
  const int8_t* wt = w->data.int8;
  for (int bt = 0; bt < in_size / depth; bt++) {
    for (int u = 0; u < units; u++) {
      int32_t acc = b ? b->data.i32[u] : 0;
      for (int k = 0; k < depth; k++) acc += (x[bt * depth + k] - d->in_zp) * (wt[u * depth + k] - d->w_zp);
      acc = tflite::MultiplyByQuantizedMultiplier(acc, d->mult, d->shift) + d->out_zp;
      out->data.int8[bt * units + u] = (int8_t)(acc < d->act_min ? d->act_min : (acc > d->act_max ? d->act_max : acc));
    }
  }
  return kTfLiteOk;
}

template <unsigned N> static void add_common_ops(tflite::MicroMutableOpResolver<N>& r) {
  r.AddPad(); r.AddConv2D(); r.AddLogistic(); r.AddMul(); r.AddStridedSlice(); r.AddTranspose(); r.AddAdd();
  r.AddConcatenation(); r.AddMaxPool2D(); r.AddSplitV(); r.AddReshape(); r.AddDepthwiseConv2D(); r.AddSplit();
  r.AddPack(); r.AddSoftmax(); r.AddQuantize(); r.AddResizeNearestNeighbor(); r.AddSub(); r.AddMean();
}
static tflite::MicroMutableOpResolver<20> cnn_ops, yolo_ops;

const char* vision_class_name(int cls) {
  static const char* const names[3] = {"NO_FLAME", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"};  // backend labels
  return (cls >= 0 && cls < 3) ? names[cls] : "UNKNOWN";
}

bool vision_ready() { return ready; }
const char* vision_status() { return status_txt; }

VisionResult vision_latest() {
  portENTER_CRITICAL(&latest_mux);
  VisionResult r = latest;
  portEXIT_CRITICAL(&latest_mux);
  return r;
}

bool vision_request(const char* reason) {
  if (!ready) return false;
  char r[24] = {};
  strncpy(r, reason, sizeof(r) - 1);
  return xQueueSend(req_q, r, 0) == pdTRUE;
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------
static uint8_t* load_file(const char* path) {
  File f = SD_MMC.open(path);
  if (!f) return nullptr;
  size_t n = f.size();
  uint8_t* b = (uint8_t*)heap_caps_aligned_alloc(16, n, MALLOC_CAP_SPIRAM);   // TFLM expects 16-byte aligned weights
  if (b && f.read(b, n) != n) { heap_caps_free(b); b = nullptr; }
  f.close();
  if (b) Serial.printf("[vision] loaded %s (%u bytes)\n", path, (unsigned)n);
  return b;
}

// The models expect int8 = pixel - 128 (CNN: scale 1 on 0-255, YOLO: scale 1/255 on 0-1). Refuse anything else.
static bool input_is_pixel_minus_128(const TfLiteTensor* t) {
  float s = t->params.scale;
  return t->type == kTfLiteInt8 && t->params.zero_point == -128 &&
         (fabsf(s - 1.0f) < 1e-3f || fabsf(s * 255.0f - 1.0f) < 1e-3f);
}

// Probe with a big arena, then rebuild with exactly what was used, so both nets fit in the 8 MB PSRAM.
static bool build(Net& n, const uint8_t* buf, const tflite::MicroOpResolver& resolver, const char* name) {
  const tflite::Model* model = tflite::GetModel(buf);
  if (model->version() != TFLITE_SCHEMA_VERSION) { Serial.printf("[vision] %s: bad schema\n", name); return false; }
  size_t largest = heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM);
  if (largest <= VISION_PSRAM_RESERVE) { Serial.printf("[vision] %s: PSRAM full\n", name); return false; }
  size_t size = largest - VISION_PSRAM_RESERVE;
  for (int pass = 0; pass < 2; pass++) {
    const size_t guard = pass ? ARENA_GUARD : 0;                  // the probe is freed right away: no guards
    uint8_t* base = (uint8_t*)heap_caps_aligned_alloc(16, size + 2 * guard, MALLOC_CAP_SPIRAM);
    if (!base) { Serial.printf("[vision] %s: arena alloc %u failed\n", name, (unsigned)size); return false; }
    uint8_t* arena = base + guard;
    auto* it = new tflite::MicroInterpreter(model, resolver, arena, size, nullptr, &op_tracker);
    if (it->AllocateTensors() != kTfLiteOk) {
      Serial.printf("[vision] %s: AllocateTensors failed (unsupported op or arena %u too small)\n", name, (unsigned)size);
      delete it; heap_caps_free(base); return false;
    }
    if (pass == 0) { size = it->arena_used_bytes() + 16 * 1024; delete it; heap_caps_free(base); continue; }
    n.it = it;
    n.lo = base; n.hi = arena + size;
    memset(n.lo, GUARD_BYTE, ARENA_GUARD);
    memset(n.hi, GUARD_BYTE, ARENA_GUARD);
  }
  Serial.printf("[vision] %s ready, arena %u KB\n", name, (unsigned)(size / 1024));
  return input_is_pixel_minus_128(n.it->input(0));
}

static bool load_all() {
  if (!psramFound()) { status_txt = "no PSRAM"; return false; }
  SD_MMC.setPins(SD_MMC_CLK_GPIO, SD_MMC_CMD_GPIO, SD_MMC_D0_GPIO);
  if (!SD_MMC.begin("/sdcard", true)) { status_txt = "no SD card"; return false; }
  uint8_t* cnn_buf = load_file(VISION_CNN_PATH);
  uint8_t* yolo_buf = load_file(VISION_YOLO_PATH);
  if (!cnn_buf || !yolo_buf) { status_txt = "model file missing"; return false; }   // buffers stay: task ends

  add_common_ops(cnn_ops);  cnn_ops.AddFullyConnected();
  add_common_ops(yolo_ops); yolo_ops.AddFullyConnected(tflite::micro::RegisterOp(fc_init, fc_prepare, fc_eval));

  const uint32_t crashed_in = (esp_reset_reason() == ESP_RST_PANIC && active_model && vision_task_panicked()) ? active_model : 0;
  active_model = 0;
  if (crashed_in == ACTIVE_CNN) { status_txt = "CNN crashed, off"; return false; }

  active_model = ACTIVE_CNN;
  bool ok = build(cnn, cnn_buf, cnn_ops, "CNN");
  active_model = 0;
  TfLiteTensor *ci = ok ? cnn.it->input(0) : nullptr, *co = ok ? cnn.it->output(0) : nullptr;
  if (!ok || ci->dims->size != 4 || co->dims->data[co->dims->size - 1] != 3 || co->type != kTfLiteInt8) {
    status_txt = "CNN init failed"; return false;
  }

  if (crashed_in == ACTIVE_YOLO) {
    Serial.println("[vision] YOLO crashed on the last boot — running CNN only.");
    return true;
  }
  active_model = ACTIVE_YOLO;
  ok = build(yolo, yolo_buf, yolo_ops, "YOLO");
  active_model = 0;
  TfLiteTensor* yo = ok ? yolo.it->output(0) : nullptr;
  if (!ok || yo->dims->size != 3 || yo->dims->data[1] != 5 || yo->type != kTfLiteInt8) {
    Serial.println("[vision] YOLO init failed — running CNN only.");
    yolo.it = nullptr;                                              // shortcut: its arena is not freed; boot-time only
  }
  return true;
}

// ---------------------------------------------------------------------------
// Preprocessing + inference
// ---------------------------------------------------------------------------
// Box filter with fractional edge weights: the device equivalent of the 'area' resize used in training.
static void area_resize_q(const uint8_t* src, int sw, int sh, int8_t* dst, int dw, int dh, int dst_stride) {
  const float fx = (float)sw / dw, fy = (float)sh / dh;
  for (int oy = 0; oy < dh; oy++) {
    const float y0 = oy * fy, y1 = y0 + fy;
    for (int ox = 0; ox < dw; ox++) {
      const float x0 = ox * fx, x1 = x0 + fx;
      float acc[3] = {0, 0, 0}, wsum = 0;
      for (int y = (int)y0; y < sh && y < y1; y++) {
        const float wy = fminf(y1, y + 1) - fmaxf(y0, y);
        for (int x = (int)x0; x < sw && x < x1; x++) {
          const float w = wy * (fminf(x1, x + 1) - fmaxf(x0, x));
          const uint8_t* p = src + (y * sw + x) * 3;
          acc[0] += w * p[0]; acc[1] += w * p[1]; acc[2] += w * p[2]; wsum += w;
        }
      }
      int8_t* o = dst + (oy * dst_stride + ox) * 3;
      for (int c = 0; c < 3; c++) o[c] = (int8_t)((int)(acc[c] / wsum + 0.5f) - 128);
    }
  }
}

static float deq(const TfLiteTensor* t, int i) { return (t->data.int8[i] - t->params.zero_point) * t->params.scale; }

static float iou(const float* a, const float* b) {
  float ix = fmaxf(0, fminf(a[2], b[2]) - fmaxf(a[0], b[0])), iy = fmaxf(0, fminf(a[3], b[3]) - fmaxf(a[1], b[1]));
  float inter = ix * iy;
  return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9f);
}

static void run_cnn(const uint8_t* rgb, int w, int h, VisionResult& r) {
  TfLiteTensor* in = cnn.it->input(0);
  area_resize_q(rgb, w, h, in->data.int8, in->dims->data[2], in->dims->data[1], in->dims->data[2]);
  check_guards("before CNN Invoke");
  last_op_idx = 0;
  unsigned long t0 = millis();
  active_model = ACTIVE_CNN;
  TfLiteStatus st = cnn.it->Invoke();
  active_model = 0;
  check_guards("after CNN Invoke");
  if (st != kTfLiteOk) { Serial.println("[vision] CNN Invoke failed."); return; }
  r.cnn_ms = millis() - t0;
  TfLiteTensor* out = cnn.it->output(0);
  for (int c = 0; c < 3; c++) {
    float p = deq(out, c);
    if (c == 0 || p > r.cnn_conf) { r.cnn_conf = p; r.cnn_cls = c; }
  }
  r.valid = true;
}

static void run_yolo(const uint8_t* rgb, int w, int h, VisionResult& r) {
  TfLiteTensor* in = yolo.it->input(0);
  const int S = in->dims->data[1];                                  // 160 (square input)
  const float k = fminf((float)S / w, (float)S / h);
  const int nw = (int)roundf(w * k), nh = (int)roundf(h * k), px = (S - nw) / 2, py = (S - nh) / 2;
  memset(in->data.int8, 114 - 128, S * S * 3);                      // ultralytics letterbox grey
  area_resize_q(rgb, w, h, in->data.int8 + (py * S + px) * 3, nw, nh, S);
  check_guards("before YOLO Invoke");
  last_op_idx = 0;
  unsigned long t0 = millis();
  active_model = ACTIVE_YOLO;
  TfLiteStatus st = yolo.it->Invoke();
  active_model = 0;
  check_guards("after YOLO Invoke");
  if (st != kTfLiteOk) { Serial.println("[vision] YOLO Invoke failed."); return; }
  r.yolo_ms = millis() - t0;
  r.yolo_ok = true;

  TfLiteTensor* out = yolo.it->output(0);
  const int N = out->dims->data[2];
  r.n_boxes = 0;
  // Greedy NMS: repeatedly take the best remaining box that does not overlap a kept one.
  // shortcut: O(N * MAX_BOXES) rescans of the 525 anchors, fine at 160 px; upgrade if the input size grows.
  float taken = 2.0f;                                               // score of the last box taken
  while (r.n_boxes < VISION_MAX_BOXES) {
    float best[5] = {0, 0, 0, 0, 0};
    for (int j = 0; j < N; j++) {
      float s = deq(out, 4 * N + j);
      if (s < VISION_YOLO_CONF || s >= taken || s <= best[4]) continue;
      float cx = deq(out, j) * S, cy = deq(out, N + j) * S, bw = deq(out, 2 * N + j) * S, bh = deq(out, 3 * N + j) * S;
      float b[5] = {fmaxf(0, (cx - bw / 2 - px) / nw), fmaxf(0, (cy - bh / 2 - py) / nh),
                    fminf(1, (cx + bw / 2 - px) / nw), fminf(1, (cy + bh / 2 - py) / nh), s};
      bool overlaps = false;
      for (int i = 0; i < r.n_boxes && !overlaps; i++) overlaps = iou(b, r.boxes[i]) >= VISION_YOLO_NMS_IOU;
      if (!overlaps) memcpy(best, b, sizeof(best));
    }
    if (best[4] == 0) break;
    memcpy(r.boxes[r.n_boxes++], best, sizeof(best));
    taken = best[4];
  }
}

static VisionResult analyse(uint8_t* jpg, size_t len) {
  VisionResult r = {};
  esp_jpeg_image_cfg_t cfg = {};
  cfg.indata = jpg; cfg.indata_size = len;
  cfg.out_format = JPEG_IMAGE_FORMAT_RGB888;                        // tjpgd byte order R,G,B
  cfg.out_scale = JPEG_IMAGE_SCALE_1_4;                             // SVGA -> 200x150
  esp_jpeg_image_output_t info;
  if (esp_jpeg_get_image_info(&cfg, &info) != ESP_OK) { Serial.println("[vision] JPEG header unreadable."); return r; }
  cfg.outbuf_size = info.output_len;
  cfg.outbuf = (uint8_t*)heap_caps_malloc(cfg.outbuf_size, MALLOC_CAP_SPIRAM);
  if (!cfg.outbuf) return r;
  if (esp_jpeg_decode(&cfg, &info) != ESP_OK) Serial.println("[vision] JPEG decode failed.");
  else {
    run_cnn(cfg.outbuf, info.width, info.height, r);
    if (r.valid && yolo.it) run_yolo(cfg.outbuf, info.width, info.height, r);
  }
  heap_caps_free(cfg.outbuf);
  r.at_ms = millis();
  return r;
}

// ---------------------------------------------------------------------------
// Task: same core and priority as loop() so FreeRTOS time-slices them; loop() never waits on inference.
// ---------------------------------------------------------------------------
static void vision_task(void*) {
  if (!load_all()) {
    Serial.printf("[vision] disabled: %s — snapshots upload without on-device classification.\n", status_txt);
    vTaskDelete(nullptr);
  }
  status_txt = yolo.it ? "ready" : "ready (CNN only)";
  ready = true;
  Serial.printf("[vision] %s.\n", yolo.it ? "CNN + YOLO ready" : "CNN ready, YOLO off");

  char reason[24];
  for (;;) {
    if (xQueueReceive(req_q, reason, portMAX_DELAY) != pdTRUE) continue;
    camera_fb_t* fb = camera_capture(true);
    if (!fb) continue;
    size_t len = fb->len;
    uint8_t* jpg = (uint8_t*)heap_caps_malloc(len, MALLOC_CAP_SPIRAM);
    if (jpg) memcpy(jpg, fb->buf, len);
    camera_return_fb(fb);
    if (!jpg) continue;

    VisionResult r = analyse(jpg, len);
    if (r.valid) {
      portENTER_CRITICAL(&latest_mux); latest = r; portEXIT_CRITICAL(&latest_mux);
      Serial.printf("[vision] %s: %s %.0f%% (%lu ms) | %d flame box(es) (%lu ms)\n", reason, vision_class_name(r.cnn_cls),
                    r.cnn_conf * 100, (unsigned long)r.cnn_ms, r.n_boxes, (unsigned long)r.yolo_ms);
    }
    if (!network_enqueue_snapshot_jpeg(reason, jpg, len, r)) heap_caps_free(jpg);   // queue owns jpg on success
  }
}

void vision_init() {
  req_q = xQueueCreate(3, 24);
  xTaskCreatePinnedToCore(vision_task, "vision", 16384, nullptr, 1, nullptr, 1);
}
