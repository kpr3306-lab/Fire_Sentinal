# Backend: YOLO flame detector + hazard logic

Every uploaded snapshot now goes through: CNN classify -> YOLO detect -> hazard assessment -> saved in `snapshots`.
Both models are optional; the upload route never fails because of them.

## Files (all paths relative to your `backend\` folder)
NEW    services\yolo_service.py        runs fire_yolo.pt, returns boxes + flame area share (never raises)
NEW    services\hazard_service.py      CNN class + flame size + growth -> NONE / CONTROLLED / HAZARDOUS / UNKNOWN
NEW    tests\test_hazard_pipeline.py   9 tests, no weights needed
NEW    models\README_models.txt        weights go in this folder
CHANGE routes\camera_routes.py         ~15 lines in upload_snapshot (+ extra fields in its JSON reply)
CHANGE db.py                           adds the new columns to an EXISTING database file on startup (idempotent)
CHANGE database\schema.sql             same columns for a brand-new database
CHANGE config.py                       YOLO path/threshold + hazard thresholds (PLACEHOLDERS, see below)
CHANGE requirements.txt                numpy, Pillow, ai-edge-litert, ultralytics appended

Back up your `backend\` folder first: config.py, db.py, schema.sql, camera_routes.py and requirements.txt are REPLACED.
If you edited any of them since the v-3 zip, merge by hand instead of overwriting.

## Steps (PowerShell, backend venv active)
1. Copy the files above over your backend folder.
2. Copy the weights:  copy ..\ml\yolo\artifacts\fire_yolo.pt models\fire_yolo.pt      (adjust the path to where yours is)
3. pip install numpy Pillow ultralytics           (ultralytics pulls in PyTorch: large download)
4. python -m unittest tests.test_hazard_pipeline -v          -> should end with OK (9 tests)
5. python run.py        -> an existing database is upgraded automatically on start
6. Post a test snapshot (use a device_id that exists in your devices table):
   curl.exe -F device_id=YOUR_DEVICE -F reason=on_demand -F "image=@C:\path\to\flame.jpg" http://localhost:5000/api/camera/snapshot
   Reply should show "detector_status": "ok", "hazard_level", "flame_count".
7. curl.exe "http://localhost:5000/api/camera/snapshots?limit=3"   -> rows now carry flame_boxes (JSON text), flame_area_ratio, flame_growth, hazard_level, hazard_reasons.

## Hazard rules (services\hazard_service.py)
HAZARDOUS  if ANY: CNN says HAZARDOUS_FIRE | flame area >= HAZARD_AREA_RATIO | area grew >= HAZARD_GROWTH_RATIO x since the previous snapshot
           of the same device within HAZARD_GROWTH_WINDOW_S (and area >= HAZARD_GROWTH_MIN_AREA).
CONTROLLED flame evidence (CNN says controlled, or the detector sees a flame) but small and not growing.
NONE       CNN says NO_FLAME and the detector found nothing.
UNKNOWN    no usable evidence. "Detector found nothing" is never treated as proof of no fire (box recall is only ~57%).
Every row stores hazard_reasons so you can see WHY.

## IMPORTANT: thresholds are placeholders
config.py defaults (15% of frame, 1.5x growth, 1% min area, 180 s window) are rough guesses from training-set box sizes, NOT calibrated.
Weakness: a close-up of a harmless stove flame can fill much of the frame and trip the area rule.
Tune with env vars (HAZARD_AREA_RATIO, ...) on real OV3660 footage: a small stable flame vs a spreading one.
YOLO_CONF (default 0.25): choose it from BoxF1_curve.png in your Colab outputs.

## What was and wasn't verified
Verified (9 passing tests on a throwaway database with fake detections): the hazard decision table, union-area maths, missing-weights path,
parsing of the Ultralytics result shape (attribute names checked against ultralytics 8.4.182 source), the upload route end to end including growth
between two snapshots and ignoring stale snapshots, listing endpoint, and the migration of an old database (run twice).
NOT verified: a real prediction with fire_yolo.pt (sandbox had no room for PyTorch) and real-camera behaviour. First real run is yours — paste any error.
NOT changed: the dashboard (it still shows its old fields; boxes could be drawn on the gallery later), risk_score_service / alerts (they don't read hazard_level yet),
and the CNN service (install the real ml_inference_service.py from the CNN kit separately, with FIRE_MODEL_PATH set).
