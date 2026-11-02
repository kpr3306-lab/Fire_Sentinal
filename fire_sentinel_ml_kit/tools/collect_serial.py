"""
tools/collect_serial.py — record one labelled sensor session from the ESP32-S3's serial port.

The firmware prints one line per second:  CSV,<ms>,<temp>,...   (see sensor_common.CSV_COLUMNS)
This script keeps only those lines, adds the label you give it, and writes
    ml/sensor/dataset/raw/<LABEL>__<scenario>__<YYYYmmdd_HHMMSS>.csv

Run from the fire_sentinel_ml_kit folder (PowerShell):
    pip install pyserial
    python tools/collect_serial.py --list-ports
    python tools/collect_serial.py --port COM5 --label NORMAL --scenario bedroom_evening --minutes 10

Use the UART USB port of the board (the one that shows up as a COM port), not the native USB port.
The timer counts only rows with b_ready=1 (baseline learned + MQ heaters warmed up, ~4-5 min after power-up);
rows before that are saved too but are ignored by training.
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime

COLUMNS = ["ms", "temp", "hum", "pres", "mq2", "mq7", "mq135", "uv", "flame", "valid", "state", "risk",
           "b_temp", "b_mq2", "b_mq7", "b_mq135", "b_uv", "b_ready"]
LABELS = ["NORMAL", "CONTROLLED_FLAME", "HAZARDOUS_FIRE"]

SAFETY = """
SAFETY — read before recording a flame / fire session
  * Controlled flame: candle, lighter or gas stove used normally, adult present, nothing flammable nearby.
  * Hazardous-fire signature: only a very small source (e.g. one sheet of paper) in a metal tray/bucket,
    OUTDOORS or in a well-ventilated lab area, with a fire extinguisher / water to hand and someone supervising.
    Keep the board and your laptop at a safe distance. Never leave it unattended. Stop at the first sign it is not controlled.
  * Do NOT create real fires indoors for the sake of data. A dataset with fewer fire sessions is better than an injury.
"""


def list_ports():
    from serial.tools import list_ports as lp
    ports = list(lp.comports())
    if not ports:
        print("No serial ports found.")
    for p in ports:
        print(f"  {p.device}  {p.description}")


def main():
    ap = argparse.ArgumentParser(description="Record a labelled sensor session")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--scenario", default="unspecified", help="short tag, e.g. kitchen_kettle, candle_1m, paper_tray_outdoor")
    ap.add_argument("--minutes", type=float, default=10.0, help="minutes of READY data to record")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default=os.path.join("ml", "sensor", "dataset", "raw"))
    ap.add_argument("--yes", action="store_true", help="skip the safety confirmation")
    args = ap.parse_args()

    if args.list_ports:
        list_ports(); return
    if not args.port or not args.label:
        ap.error("--port and --label are required (use --list-ports to find the port)")

    if args.label != "NORMAL" and not args.yes:
        print(SAFETY)
        if input("Type YES to continue: ").strip() != "YES":
            print("Cancelled."); return

    import serial
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_scn = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.scenario)
    path = os.path.join(args.out, f"{args.label}__{safe_scn}__{stamp}.csv")

    ser = serial.Serial(args.port, args.baud, timeout=2)
    print(f"Recording to {path}\nCtrl+C to stop early. Waiting for 'CSV,' lines from the board...")
    rows = ready_rows = 0
    t0 = time.time()
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("# fire-sentinel-sensor-session v1\n")
            f.write(f"# label={args.label}\n# scenario={args.scenario}\n# note={args.note}\n")
            f.write(f"# recorded={datetime.now().isoformat(timespec='seconds')}\n")
            w = csv.writer(f)
            w.writerow(COLUMNS)
            while ready_rows < args.minutes * 60:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line.startswith("CSV,"):
                    continue
                parts = line.split(",")[1:]
                if len(parts) != len(COLUMNS):
                    continue                                   # partial line at start-up
                w.writerow(parts)
                rows += 1
                if parts[COLUMNS.index("b_ready")] == "1":
                    ready_rows += 1
                if rows % 5 == 0:
                    print(f"\r  rows={rows}  ready={ready_rows}/{int(args.minutes*60)}  state={parts[COLUMNS.index('state')]}"
                          f"  risk={parts[COLUMNS.index('risk')]}  b_ready={parts[-1]}   ", end="", flush=True)
                if rows % 30 == 0:
                    f.flush()
    except KeyboardInterrupt:
        print("\nStopped early.")
    finally:
        ser.close()
    print(f"\nSaved {rows} rows ({ready_rows} usable) in {time.time()-t0:.0f}s -> {path}")
    if ready_rows < 60:
        print("WARNING: fewer than 60 usable rows — training needs windows of 30 s with b_ready=1. "
              "Wait for the baseline (about 4-5 min after power-up) before recording.")


if __name__ == "__main__":
    sys.exit(main())
