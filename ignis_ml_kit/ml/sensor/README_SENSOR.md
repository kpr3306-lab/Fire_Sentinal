# Ignis — sensor model kit (stage 1-3 of the sensor ML plan)

| Stage | What | Where it runs |
|---|---|---|
| 1. Baseline calibration (not ML) | per-device "normal" for gas/temperature/UV | on the ESP32 (`sensors.cpp`); every CSV row carries the baseline that was active |
| 2. Classifier | RandomForest on 30 s window features: NORMAL / CONTROLLED_FLAME / HAZARDOUS_FIRE | trained on your PC, exported to C, runs on the ESP32 |
| 3. Anomaly detector | IsolationForest trained on NORMAL windows only: "this is not normal" even for fires you never recorded | same |

**Training happens on your PC** (not on the ESP32, not on the backend). Nothing here needs TensorFlow.

## Where everything is stored
| What | Path |
|---|---|
| Recorded sessions (your data) | `ml/sensor/dataset/raw/<LABEL>__<scenario>__<time>.csv` |
| Trained models, manifest, report, plots | `ml/sensor/artifacts/` (`sensor_rf.joblib`, `sensor_iforest.joblib`, `sensor_model_manifest.json`, `sensor_report.md`, PNGs) |
| Model for the firmware | `ml/sensor/firmware_src/sensor_model.h` -> copied into the sketch folder, compiled into **flash** (no SD card) |
| Inference code for the firmware | `ml/sensor/firmware_src/sensor_ml.h / sensor_ml.cpp` (already in firmware v2.2) |

## Steps (PowerShell, from the `ignis_ml_kit` folder)
```powershell
pip install scikit-learn pandas numpy joblib matplotlib pyserial

# 0. Smoke test with SYNTHETIC data (invented numbers — checks the pipeline only, never quote the results)
python tools/make_demo_data.py
python ml/sensor/train_sensor.py --data ml/sensor/dataset/demo_synthetic --out ml/sensor/artifacts_demo

# 1. Record real sessions (board on, wait ~4-5 min for b_ready=1, UART USB port)
python tools/collect_serial.py --list-ports
python tools/collect_serial.py --port COM5 --label NORMAL --scenario bedroom_evening --minutes 10

# 2. Train + report
python ml/sensor/train_sensor.py
#    read ml/sensor/artifacts/sensor_report.md

# 3. Export and flash
python ml/sensor/export_c.py --firmware-dir "C:\path\to\esp32s3_cam_main"
#    recompile + upload the sketch; the serial log prints the model version at boot
```

## What data to record (this decides whether the model is any good)
* **At least 6 sessions per class, over different days / times / places**, 10 minutes of ready data each. The script refuses to train with <2 sessions/class and warns below 4.
* **NORMAL**: idle room, plus ordinary disturbances (kettle/steam at a distance, door open, fan/AC, day vs night). The anomaly detector only knows what "normal" looks like from these.
* **CONTROLLED_FLAME**: candle / lighter / gas stove used normally.
* **HAZARDOUS_FIRE**: only a very small, supervised source (e.g. one sheet of paper in a metal tray, outdoors or well ventilated, extinguisher/water at hand, board and laptop at a distance). Never make fires indoors for data. Fewer fire sessions is better than an injury.
* Keep the sensor placement the same as in deployment.

## Why the evaluation is honest
Neighbouring windows overlap by 29/30 samples, so a random train/test split would leak and look perfect. `train_sensor.py` evaluates **leave-one-session-out**: a recording is never in both train and test. The report gives per-class recall, NORMAL->HAZARDOUS false alarms, the anomaly detector's false-positive rate on held-out NORMAL sessions, and AUROC against fire windows it never trained on.

## Using the model on the device
* Default `SENSOR_ML_AFFECTS_SCORE 0` (config.h): the model is **advisory** — result goes to the backend (`ml_json`) and the serial log, alarm logic is unchanged.
* After you have validated it on real data set it to `1`: the model can then only **raise** the rule-based score, never lower it.
* The firmware inference code is verified against scikit-learn: `tests/test_parity.py` compiles the real `sensor_ml.cpp` and compares features, class probabilities and anomaly scores.
```powershell
$env:FIRMWARE_DIR = "C:\path\to\esp32s3_cam_main"     # needs g++ (MSYS2/MinGW); skipped otherwise
python -m unittest ml/sensor/tests/test_parity.py -v
```

## Keep in sync
`sensor_common.py` mirrors `WINDOW_SIZE`, `SENSOR_SAMPLE_INTERVAL_MS`, `MQ_MIN_BASELINE_RAW`, `UV_FULL_SCALE_COUNTS` from the firmware's `config.h` (the parity test checks this). If you change the window length, sampling rate or feature list, record new data and retrain.

## Known limits
* Window features use the debounced flame input and the on-device baseline; train and run with the same firmware version.
* No real data exists yet: any numbers before you record sessions come from synthetic data and mean nothing.
* MQ sensors drift with age/temperature/humidity; re-check performance after weeks of use.
