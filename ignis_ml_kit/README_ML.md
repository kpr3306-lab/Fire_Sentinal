# Ignis — CNN training kit

Run every command below from the `ignis_ml_kit/` folder.

```
ml/cnn/cnn_common.py          shared helpers (class order is FIXED: no_fire, controlled_flame, hazardous_fire)
ml/cnn/train_cnn.py           MobileNetV2 transfer learning, 3-way softmax, 2-phase (head, then fine-tune)
ml/cnn/evaluate.py            accuracy, per-class P/R/F1, confusion matrix PNG, hazardous misses, threshold sweep
ml/cnn/quantize_int8.py       FP32 + full-integer INT8 .tflite, prints input scale/zero-point for firmware
ml/cnn/benchmark.py           Keras vs TFLite-FP32 vs TFLite-INT8: size, accuracy, hazardous recall, host latency
tools/dataset_split.py        dedupe + leakage-safe train/val/test split
tools/model_manifest_generator.py   writes ml/cnn/model_manifest.json (already read by GET /api/model-info)
backend_services/ml_inference_service.py   REAL version -> replace backend/services/ml_inference_service.py
```

## 1. Collect images → `ml/cnn/dataset/raw/`

```
raw/no_fire/<session>/*.jpg          raw/controlled_flame/<session>/*.jpg          raw/hazardous_fire/<session>/*.jpg
```

**Put every video / shoot / source in its own sub-folder** (`yt_kitchen_fire_clip2/`, `my_candle_evening/`). The splitter keeps a whole
sub-folder inside ONE split — this is what stops near-identical video frames inflating your test accuracy. Keep a `sources.md` (provenance + licence).

| Class | What goes in | Hard cases you MUST include |
|---|---|---|
| no_fire | normal rooms, kitchens, corridors, outdoors | sunset/sunlight through windows, orange/red objects, lamps, LEDs, TV screens, stove burners OFF, steam, incense/dust haze, low light |
| controlled_flame | candles, gas stove burner, lighter, small campfire/diya | different distances, partially occluded flame, lit-room vs dark-room |
| hazardous_fire | spreading/uncontrolled fire, large flames, heavy smoke + flame | indoor + outdoor, day + night, flame at distance |

Targets (blueprint says ~10K): roughly 3.5K / 3K / 3.5K. **Min 100–150 per class per session-type is useless if they are all one video — diversity of
scenes matters more than count.** Aim for ≥ 15% of images captured by your own OV3660 at the exact firmware settings (SVGA JPEG q12), because the
Kaggle-style web images have a different colour/noise profile from your sensor (domain shift is the #1 reason a model that scores 98% offline disappoints on the board).
Capture only the safe classes yourself (no_fire, supervised candle/stove); source hazardous_fire from public datasets/videos — don't stage real fires.
The Snapshot Gallery images in `backend/storage/snapshots/` can be dragged straight into the class folders.

## 2. Run order

```bash
pip install -r requirements_ml.txt
python tools/dataset_split.py --raw ml/cnn/dataset/raw --out ml/cnn/dataset/split          # read split_report.json + label_conflicts.txt
cd ml/cnn
python train_cnn.py --data dataset/split --img 96 --alpha 0.35
python quantize_int8.py --model artifacts/fire_cnn.keras --data dataset/split --img 96
python evaluate.py --model artifacts/fire_cnn.keras      --data dataset/split --img 96 --tag fp32
python evaluate.py --model artifacts/fire_cnn_int8.tflite --data dataset/split --img 96 --tag int8
python benchmark.py --data dataset/split --img 96
cd ../..
python tools/model_manifest_generator.py --version 1.0.0
```
Copy `ml/cnn/artifacts/fire_cnn_int8.tflite` + `model_manifest.json` to the SD card `/model/`. The backend picks the model up automatically (reloads if the file changes).
GPU not needed at this size, but Colab is fine; MobileNetV2 ImageNet weights download on first run (needs internet).

## 3. Decisions baked in (change via flags; tell me if you disagree)

- **Input 96×96, MobileNetV2 α=0.35** — the smallest official pretrained variant, comfortably inside TFLite Micro's tensor arena on 8 MB PSRAM. The blueprint leaves this open
  ("decide after real RAM/latency numbers"). Once the INT8 model is on the S3, measure `Invoke()` time + arena use; if headroom is large, retrain at `--img 128 --alpha 0.5` and compare in `benchmark.py`.
- **Recall-biased:** hazardous_fire class weight ×1.5 (`--haz-weight`). The confusion matrix reports the *dangerous* error (hazardous→anything else), the *worst* error (hazardous→no_fire) and the *false-alarm* rate separately, plus a P(hazardous) threshold sweep, so you can justify the operating point at the viva.
- **Rescaling is inside the model** → firmware feeds raw RGB 0–255 as `int8 = round(pixel/scale) + zero_point` (smoke test gave scale≈1.0, zp=−128, i.e. `pixel − 128`). Exact values are in `quant_info.json` and the manifest.
- **Resize method matters:** training uses `area` (box) downscale from the original image. The firmware must downscale the 800×600 frame the same way (box/area average), not nearest-neighbour or a bare bilinear pick, or accuracy on-device will quietly drop. The backend service already uses `Image.BOX` to match.
- Splits are 70/15/15, grouped by session, near-duplicates (pHash ≤ 4) merged, cross-class near-duplicates dropped as probable label errors.

## 4. What was and wasn't verified

Verified in a sandbox on synthetic images: the splitter (planted duplicate + planted cross-class conflict were caught, no group spans two splits), train → FP32/INT8 export → evaluate → benchmark → manifest all run end-to-end, and the backend service returns a label for a valid image, `PENDING_MODEL` for a corrupt/missing image or missing model file, and was safe under 16 concurrent threads.
**Not verified:** actual learning quality (needs your real images + ImageNet weights, which the sandbox couldn't download) and on-device latency/arena. Also the sandbox's Keras 3 build had a bug that broke even a trivial `fit()`, so I validated under `TF_USE_LEGACY_KERAS=1` (tf-keras). On a normal TF ≥ 2.16 install Keras 3 should work with no changes — if you hit a Keras-3 error, send me the traceback, or `pip install tf-keras` and `set TF_USE_LEGACY_KERAS=1` as a fallback.

## 5. Small cleanups noticed in your v-3 zip

- `firmware/.../camera.cpp` header comment still says OV2640 — it's the OV3660 (PID 0x3660).
- The zip ships `backend/venv/`, `backend/.env` and `__pycache__` (~100 MB). Don't submit/commit those; `.env` holds your Telegram/SMTP secrets.
