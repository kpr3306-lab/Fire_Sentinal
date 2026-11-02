"""
ml/yolo/train_yolo.py — train a YOLO11n flame detector on the dataset made by tools/prepare_yolo_dataset.py,
evaluate it on the held-out TEST split, and copy the best weights to ml/yolo/artifacts/fire_yolo.pt.

Local / Colab:
    pip install ultralytics
    python ml/yolo/train_yolo.py --data ml/yolo/dataset --epochs 50 --imgsz 640

Smaller/faster experiments: --imgsz 416 or 320.  CPU-only training is slow; use a GPU (Colab T4 is fine) if you can.
"""
import argparse, json, os, shutil
import yaml
from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="dataset folder containing fire.yaml, images/, labels/")
    ap.add_argument("--model", default="yolo11n.pt", help="starting weights (downloaded on first use)")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--patience", type=int, default=15, help="stop early if val mAP stops improving")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--device", default=None, help="'0' for first GPU, 'cpu', or leave empty for auto")
    ap.add_argument("--out", default="ml/yolo/artifacts")
    a = ap.parse_args()

    data_dir = os.path.abspath(a.data)
    with open(os.path.join(data_dir, "fire.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["path"] = data_dir                                   # Ultralytics needs an absolute dataset root
    abs_yaml = os.path.join(data_dir, "fire_abs.yaml")
    with open(abs_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    os.makedirs(a.out, exist_ok=True)
    runs = os.path.abspath(os.path.join(a.out, "runs"))
    model = YOLO(a.model)
    model.train(data=abs_yaml, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, patience=a.patience,
                workers=a.workers, device=a.device, project=runs, name="fire_yolo", exist_ok=True,
                seed=42, plots=True)
    best = os.path.join(runs, "fire_yolo", "weights", "best.pt")
    final = os.path.join(a.out, "fire_yolo.pt")
    shutil.copy2(best, final)

    m = YOLO(final).val(data=abs_yaml, split="test", imgsz=a.imgsz, device=a.device, plots=True,
                        project=runs, name="fire_yolo_test", exist_ok=True)
    res = {"weights": final, "imgsz": a.imgsz, "classes": list(cfg["names"].values()),
           "test_precision": float(m.box.mp), "test_recall": float(m.box.mr),
           "test_mAP50": float(m.box.map50), "test_mAP50_95": float(m.box.map)}
    with open(os.path.join(a.out, "yolo_test_metrics.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))
    print("saved", final)


if __name__ == "__main__":
    main()
