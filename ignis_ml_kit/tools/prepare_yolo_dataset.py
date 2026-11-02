"""
tools/prepare_yolo_dataset.py — merge several Roboflow YOLOv8 datasets into ONE clean YOLO dataset.

Why: the three Roboflow sets use different class names, come pre-split (with augmented copies of the same
photo spread across train/valid/test) and don't agree on what counts as "fire". This script
  1. reads each dataset's data.yaml and decides which source classes are flames (smoke / 'non fire' boxes dropped),
  2. remaps them to the target classes,
  3. pools every image, groups augmented copies of the same original (the part before '.rf.'),
  4. clusters near-duplicates (also mirrored ones) and splits 70/15/15 so no cluster crosses a split,
  5. writes images/ labels/ fire.yaml + prepare_report.json.

Modes
  --mode single     one class: fire                       (RECOMMENDED: hazard is derived later from flame size/growth)
  --mode two_class  controlled_flame / hazardous_fire     (class decided per DATASET via "role" in the config -- an assumption)

Steps
  python tools/prepare_yolo_dataset.py --config ml/yolo/yolo_sources.json --inspect        # look first, change nothing
  python tools/prepare_yolo_dataset.py --config ml/yolo/yolo_sources.json --out ml/yolo/dataset --mode single
Needs: pip install pyyaml imagehash pillow numpy
"""
import argparse, csv, json, os, random, re, shutil, sys
from collections import Counter, defaultdict
import numpy as np
import yaml
from PIL import Image
import imagehash

EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLIT_DIRS = ["train", "valid", "val", "test"]
NEG = re.compile(r"(^|[^a-z])(non|no|not)[\s_\-]*(fire|flame)|nofire|nonfire")


def class_names(root):
    with open(os.path.join(root, "data.yaml"), encoding="utf-8") as f:
        d = yaml.safe_load(f)
    n = d["names"]
    return [n[k] for k in sorted(n)] if isinstance(n, dict) else list(n)


def auto_flame_ids(names):
    ids = []
    for i, nm in enumerate(names):
        low = str(nm).lower()
        if ("fire" in low or "flame" in low) and not NEG.search(low):
            ids.append(i)
    return ids


def flame_ids_for(src, names):
    if "fire_class_ids" in src: return list(src["fire_class_ids"])
    if "fire_class_names" in src:
        want = {s.lower() for s in src["fire_class_names"]}
        return [i for i, n in enumerate(names) if str(n).lower() in want]
    return auto_flame_ids(names)


def parse_label(path):
    """-> list of (cls, cx, cy, w, h); polygons are converted to their bounding box."""
    out = []
    if path is None or not os.path.exists(path): return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            p = line.split()
            if len(p) < 5: continue
            try:
                c = int(float(p[0])); v = [float(x) for x in p[1:]]
            except ValueError:
                continue
            if len(v) == 4:
                cx, cy, w, h = v
            else:                                   # segmentation polygon: x1 y1 x2 y2 ...
                xs, ys = v[0::2], v[1::2]
                if not xs or not ys: continue
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
            out.append((c, cx, cy, w, h))
    return out


def gather(src):
    root = src["path"]
    if not os.path.isdir(root): sys.exit(f"[{src['name']}] folder not found: {root}")
    if not os.path.exists(os.path.join(root, "data.yaml")): sys.exit(f"[{src['name']}] no data.yaml in {root}")
    items = []
    for s in SPLIT_DIRS:
        idir = os.path.join(root, s, "images"); ldir = os.path.join(root, s, "labels")
        if not os.path.isdir(idir): continue
        for fn in sorted(os.listdir(idir)):
            if os.path.splitext(fn)[1].lower() not in EXT: continue
            lp = os.path.join(ldir, os.path.splitext(fn)[0] + ".txt")
            items.append({"img": os.path.join(idir, fn), "lbl": lp if os.path.exists(lp) else None,
                          "source": src["name"], "orig_split": s})
    return items


def inspect(sources):
    for src in sources:
        names = class_names(src["path"]); fids = flame_ids_for(src, names); items = gather(src)
        print(f"\n=== {src['name']}  ({src['path']})")
        print("  classes:", dict(enumerate(names)))
        print("  treated as FLAME:", {i: names[i] for i in fids} or "NONE  <-- set fire_class_names in the config")
        print("  images:", len(items), dict(Counter(i["orig_split"] for i in items)))
        cnt, areas, empty, with_flame, poly = Counter(), [], 0, 0, 0
        for it in items:
            boxes = parse_label(it["lbl"])
            if not boxes: empty += 1
            for c, cx, cy, w, h in boxes: cnt[names[c] if c < len(names) else c] += 1
            fb = [b for b in boxes if b[0] in fids]
            if fb: with_flame += 1
            areas += [b[3] * b[4] for b in fb]
            if it["lbl"] and os.path.exists(it["lbl"]) and any(len(l.split()) > 5 for l in open(it["lbl"], encoding="utf-8")): poly += 1
        print("  boxes per class:", dict(cnt))
        print(f"  images with a flame box: {with_flame}   images with NO boxes at all (background): {empty}   polygon-label files: {poly}")
        if areas:
            a = np.array(areas)
            print("  flame box area as share of image  p10/p50/p90: " + " / ".join(f"{np.percentile(a, p):.3f}" for p in (10, 50, 90)))
    print("\nIf a dataset shows 'FLAME: NONE' or the wrong classes, edit fire_class_names for it in the config.")


class UF:
    def __init__(s, n): s.p = list(range(n))
    def f(s, a):
        while s.p[a] != a: s.p[a] = s.p[s.p[a]]; a = s.p[a]
        return a
    def u(s, a, b): s.p[s.f(a)] = s.f(b)


def group_key(it):
    stem = os.path.splitext(os.path.basename(it["img"]))[0]
    return f"{it['source']}/{stem.split('.rf.')[0]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="ml/yolo/dataset")
    ap.add_argument("--mode", choices=["single", "two_class"], default="single")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.70, 0.15, 0.15])
    ap.add_argument("--phash-dist", type=int, default=4)
    ap.add_argument("--max-per-group", type=int, default=0, help="cap augmented copies of one original (0 = keep all)")
    ap.add_argument("--min-box", type=float, default=1e-4, help="drop boxes whose area share is below this")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8")); sources = cfg["sources"]
    if a.inspect: return inspect(sources)

    target_names = ["fire"] if a.mode == "single" else ["controlled_flame", "hazardous_fire"]
    items, stats = [], defaultdict(Counter)
    for src in sources:
        names = class_names(src["path"]); fids = set(flame_ids_for(src, names))
        if not fids: sys.exit(f"[{src['name']}] no flame class detected — run --inspect and set fire_class_names")
        tgt = 0 if a.mode == "single" else (0 if src.get("role") == "controlled" else 1)
        if a.mode == "two_class" and src.get("role") not in ("controlled", "hazardous"):
            sys.exit(f"[{src['name']}] two_class mode needs role: 'controlled' or 'hazardous' in the config")
        for it in gather(src):
            boxes = []
            for c, cx, cy, w, h in parse_label(it["lbl"]):
                if c not in fids: stats[src["name"]]["dropped_other_class_boxes"] += 1; continue
                x0, y0, x1, y1 = max(0, cx - w / 2), max(0, cy - h / 2), min(1, cx + w / 2), min(1, cy + h / 2)
                w2, h2 = x1 - x0, y1 - y0
                if w2 * h2 < a.min_box: stats[src["name"]]["dropped_tiny_boxes"] += 1; continue
                boxes.append((tgt, (x0 + x1) / 2, (y0 + y1) / 2, w2, h2))
            it["boxes"] = boxes; it["group"] = group_key(it); items.append(it)

    rng = random.Random(a.seed)
    if a.max_per_group > 0:                      # thin out Roboflow augmentation copies
        by = defaultdict(list)
        for it in items: by[it["group"]].append(it)
        items = [x for g in by.values() for x in rng.sample(g, min(len(g), a.max_per_group))]

    ok = []
    for it in items:
        try:
            with Image.open(it["img"]) as im:
                im = im.convert("RGB")
                it["h"] = imagehash.phash(im); it["hf"] = imagehash.phash(im.transpose(Image.FLIP_LEFT_RIGHT))
            ok.append(it)
        except Exception as e:
            print(f"[skip unreadable] {it['img']}: {e}")
    items = ok; n = len(items)
    if n == 0: sys.exit("no usable images")

    H = np.array([i["h"].hash.flatten() for i in items], dtype=np.uint8)
    HF = np.array([i["hf"].hash.flatten() for i in items], dtype=np.uint8)
    uf = UF(n); first = {}
    for k, it in enumerate(items):
        if it["group"] in first: uf.u(k, first[it["group"]])
        else: first[it["group"]] = k
    for k in range(n):
        d = np.minimum((H[k + 1:] != H[k]).sum(1), (HF[k + 1:] != H[k]).sum(1))
        for j in np.nonzero(d <= a.phash_dist)[0]: uf.u(k, k + 1 + int(j))

    clusters = defaultdict(list)
    for k in range(n): clusters[uf.f(k)].append(k)
    names_split = ["train", "val", "test"]; split_of = {}
    strata = defaultdict(list)
    for v in clusters.values(): strata[items[v[0]]["source"]].append(v)   # keep every source in every split
    for sname, cl in strata.items():
        rng.shuffle(cl); total = sum(len(v) for v in cl)
        targets = [total * r for r in a.ratios]; got = [0, 0, 0]
        for v in sorted(cl, key=len, reverse=True):
            s = int(np.argmax([targets[i] - got[i] for i in range(3)]))
            for k in v: split_of[k] = names_split[s]
            got[s] += len(v)
    span = defaultdict(set)
    for k in range(n): span[uf.f(k)].add(split_of[k])
    assert all(len(s) == 1 for s in span.values()), "LEAKAGE: a cluster spans splits"

    if os.path.exists(a.out): shutil.rmtree(a.out)
    rows, counter = [], Counter()
    for k, it in enumerate(items):
        s = split_of[k]
        for sub in ("images", "labels"): os.makedirs(os.path.join(a.out, sub, s), exist_ok=True)
        base = f"{it['source']}_{k:06d}"
        ext = os.path.splitext(it["img"])[1].lower()
        shutil.copy2(it["img"], os.path.join(a.out, "images", s, base + ext))
        with open(os.path.join(a.out, "labels", s, base + ".txt"), "w") as f:
            for c, cx, cy, w, h in it["boxes"]: f.write(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
        counter[(s, "images")] += 1; counter[(s, "with_flame")] += bool(it["boxes"])
        for c, *_ in it["boxes"]: counter[(s, target_names[c])] += 1
        rows.append([base + ext, it["source"], s, it["group"], it["orig_split"], it["img"]])

    with open(os.path.join(a.out, "fire.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"path": ".", "train": "images/train", "val": "images/val", "test": "images/test",
                        "names": {i: nm for i, nm in enumerate(target_names)}}, f, sort_keys=False)
    with open(os.path.join(a.out, "split_manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["file", "source", "split", "group", "orig_roboflow_split", "source_path"]); w.writerows(rows)
    rep = {"mode": a.mode, "classes": target_names, "total_images": n,
           "per_split": {s: {k: counter[(s, k)] for k in ["images", "with_flame", *target_names]} for s in names_split},
           "per_source_notes": {k: dict(v) for k, v in stats.items()},
           "leakage_check": "no near-duplicate cluster or Roboflow augmentation group spans two splits"}
    json.dump(rep, open(os.path.join(a.out, "prepare_report.json"), "w"), indent=2)
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
