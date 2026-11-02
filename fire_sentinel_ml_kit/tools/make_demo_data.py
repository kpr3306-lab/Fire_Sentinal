"""
tools/make_demo_data.py — SYNTHETIC sessions to smoke-test the sensor pipeline (collect -> train -> export -> firmware).

!! These numbers are invented. A model trained on them says NOTHING about real fires and must never be reported
!! as a result. Files are written to ml/sensor/dataset/demo_synthetic/ (NOT dataset/raw) and carry '# synthetic=true',
!! which train_sensor.py copies into the manifest and the report.

    python tools/make_demo_data.py
"""
import os
import numpy as np

COLS = "ms,temp,hum,pres,mq2,mq7,mq135,uv,flame,valid,state,risk,b_temp,b_mq2,b_mq7,b_mq135,b_uv,b_ready"
OUT = os.path.join("ml", "sensor", "dataset", "demo_synthetic")


def session(label, scenario, seconds, seed, unit_scale=1.0):
    rng = np.random.default_rng(seed)
    b_temp = rng.uniform(22, 30)
    b = np.array([4200, 3100, 3600]) * unit_scale * rng.uniform(0.8, 1.25, 3)
    uv0 = rng.uniform(20, 80)
    rows = []
    t_ramp = rng.uniform(40, 120)
    for i in range(seconds):
        k = min(1.0, i / t_ramp)
        temp = b_temp + rng.normal(0, 0.05) + 0.003 * i * rng.choice([0, 1])  # slow drift
        gas = b.copy() * (1 + rng.normal(0, 0.012, 3))
        uv = uv0 + rng.normal(0, 3)
        flame = 0
        if label == "NORMAL":
            if scenario == "cooking_steam" and 100 < i < 220:
                temp += 1.5 * np.sin((i - 100) / 120 * np.pi)
                gas *= 1 + 0.18 * np.sin((i - 100) / 120 * np.pi) * np.array([1.0, 0.3, 0.6])
        elif label == "CONTROLLED_FLAME":
            flame = int(rng.random() < 0.7)
            temp += 1.2 * k
            gas *= 1 + 0.30 * k * np.array([1.0, 0.5, 0.4]) * rng.uniform(0.7, 1.3)
            uv += 250 * k
        else:  # HAZARDOUS_FIRE
            flame = int(rng.random() < 0.85)
            temp += 9 * k ** 1.3
            gas *= 1 + 1.8 * k ** 1.2 * np.array([1.0, 0.9, 0.7]) * rng.uniform(0.8, 1.2)
            uv += 900 * k
        ready = 1 if i >= 5 else 0
        rows.append(f"{1000*i + 5000},{temp:.3f},45.0,1008.0,{int(gas[0])},{int(gas[1])},{int(gas[2])},{int(uv)},{flame},1,"
                    f"NORMAL,0,{b_temp:.3f},{b[0]:.1f},{b[1]:.1f},{b[2]:.1f},{uv0:.1f},{ready}")
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    plan = []
    for i in range(6):
        plan.append(("NORMAL", "cooking_steam" if i % 3 == 0 else "idle", 360, 100 + i, 1.0 + 0.1 * i))
    for i in range(5):
        plan.append(("CONTROLLED_FLAME", "candle", 300, 200 + i, 1.0 + 0.1 * i))
    for i in range(5):
        plan.append(("HAZARDOUS_FIRE", "paper_tray", 300, 300 + i, 1.0 + 0.1 * i))
    for label, scn, secs, seed, scale in plan:
        path = os.path.join(OUT, f"{label}__{scn}__demo{seed}.csv")
        with open(path, "w") as f:
            f.write(f"# fire-sentinel-sensor-session v1\n# label={label}\n# scenario={scn}\n# synthetic=true\n{COLS}\n")
            f.write("\n".join(session(label, scn, secs, seed, scale)) + "\n")
    print(f"wrote {len(plan)} SYNTHETIC sessions to {OUT}  (pipeline smoke test only — not real data)")


if __name__ == "__main__":
    main()
