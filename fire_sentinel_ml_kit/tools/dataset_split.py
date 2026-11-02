"""
tools/dataset_split.py — dedupe + leakage-safe train/val/test split.

Input layout (what you collect):
    ml/cnn/dataset/raw/<no_fire|controlled_flame|hazardous_fire>/[<session>/]image.jpg

GROUP RULE (this is what prevents leakage): frames that come from the same
video / shooting session / source must never straddle splits, otherwise test
accuracy is inflated by near-identical neighbours. Group = sub-folder name if
the image is in one, else the filename prefix before "__", else its own group.
On top of that, near-duplicates (perceptual-hash distance <= --phash-dist, also checked against the
horizontally mirrored image so Roboflow-style flipped copies are caught) are
merged into the same group, even across sub-folders.

Cross-class near-duplicates are reported (probable label conflicts) and BOTH
copies are dropped from the split so they can't poison training.

Usage:
    python tools/dataset_split.py --raw ml/cnn/dataset/raw --out ml/cnn/dataset/split
"""
import argparse, csv, json, os, random, shutil, sys
from collections import defaultdict
import numpy as np
from PIL import Image
import imagehash

CLASSES = ["no_fire", "controlled_flame", "hazardous_fire"]
EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class UF:
    def __init__(s, n): s.p = list(range(n))
    def f(s, a):
        while s.p[a] != a:
            s.p[a] = s.p[s.p[a]]; a = s.p[a]
        return a
    def u(s, a, b): s.p[s.f(a)] = s.f(b)


def collect(raw):
    items = []
    for c in CLASSES:
        root = os.path.join(raw, c)
        if not os.path.isdir(root):
            sys.exit(f"Missing class folder: {root}")
        for dp, _, fs in os.walk(root):
            for fn in sorted(fs):
                if os.path.splitext(fn)[1].lower() not in EXT: continue
                full = os.path.join(dp, fn)
                rel = os.path.relpath(dp, root)
                if rel != ".": grp = f"{c}/{rel}"
                elif "__" in fn: grp = f"{c}/{fn.split('__')[0]}"
                else: grp = f"{c}/{os.path.splitext(fn)[0]}"
                items.append({"path": full, "cls": c, "group": grp})
    return items


def hash_all(items):
    ok = []
    for it in items:
        try:
            with Image.open(it["path"]) as im:
                im = im.convert("RGB")
                it["hash"] = imagehash.phash(im)
                it["hash_flip"] = imagehash.phash(im.transpose(Image.FLIP_LEFT_RIGHT))
                it["size"] = im.size
            ok.append(it)
        except Exception as e:
            print(f"[skip unreadable] {it['path']}: {e}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.70, 0.15, 0.15])
    ap.add_argument("--phash-dist", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-side", type=int, default=64, help="drop images smaller than this")
    a = ap.parse_args()
    assert abs(sum(a.ratios) - 1) < 1e-6

    items = hash_all(collect(a.raw))
    items = [i for i in items if min(i["size"]) >= a.min_side]
    n = len(items)
    if n == 0: sys.exit("No usable images found.")

    H = np.array([i["hash"].hash.flatten() for i in items], dtype=np.uint8)
    HF = np.array([i["hash_flip"].hash.flatten() for i in items], dtype=np.uint8)  # mirrored twins
    uf = UF(n)
    # same group -> same cluster
    first = {}
    for k, it in enumerate(items):
        if it["group"] in first: uf.u(k, first[it["group"]])
        else: first[it["group"]] = k
    # near-duplicate clustering (O(n^2) in numpy; fine for ~10-20k images)
    dup_pairs = []
    for k in range(n):
        d = np.minimum((H[k + 1:] != H[k]).sum(1), (HF[k + 1:] != H[k]).sum(1))
        for j in np.nonzero(d <= a.phash_dist)[0]:
            j = k + 1 + int(j)
            dup_pairs.append((k, j))
            if items[k]["cls"] == items[j]["cls"]:   # cross-class pairs are conflicts, never merged
                uf.u(k, j)

    # cross-class conflicts -> drop both
    drop = set()
    conflicts = []
    for i, j in dup_pairs:
        if items[i]["cls"] != items[j]["cls"]:
            drop.update([i, j]); conflicts.append((items[i]["path"], items[j]["path"]))
    # exact/near duplicates inside the same class: keep one per pair-chain member set
    seen_hash = {}
    removed_dups = 0
    for k, it in enumerate(items):
        if k in drop: continue
        root = uf.f(k)
        key = (root, it["cls"], str(it["hash"]))
        if key in seen_hash:      # identical hash inside same cluster+class -> true duplicate
            drop.add(k); removed_dups += 1
        else:
            seen_hash[key] = k
    keep = [k for k in range(n) if k not in drop]

    clusters = defaultdict(list)
    for k in keep: clusters[uf.f(k)].append(k)

    rng = random.Random(a.seed)
    split_of = {}
    names = ["train", "val", "test"]
    for c in CLASSES:
        cl = [v for v in clusters.values() if items[v[0]]["cls"] == c]
        # a cluster could in theory mix classes only via dropped conflicts; guard anyway
        cl = [[k for k in v if items[k]["cls"] == c] for v in cl]
        rng.shuffle(cl)
        total = sum(len(v) for v in cl)
        targets = [total * r for r in a.ratios]
        got = [0, 0, 0]
        for v in sorted(cl, key=len, reverse=True):   # big groups first, fill the most-behind split
            need = [targets[s] - got[s] for s in range(3)]
            s = int(np.argmax(need))
            for k in v: split_of[k] = names[s]
            got[s] += len(v)

    if os.path.exists(a.out): shutil.rmtree(a.out)
    rows = []
    for k in keep:
        it = items[k]; s = split_of[k]
        dst_dir = os.path.join(a.out, s, it["cls"]); os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{len(rows):06d}{os.path.splitext(it['path'])[1].lower()}")
        shutil.copy2(it["path"], dst)
        rows.append([dst, it["cls"], s, it["group"], it["path"]])

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "split_manifest.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["file", "class", "split", "group", "source_path"]); w.writerows(rows)

    counts = {s: {c: sum(1 for r in rows if r[2] == s and r[1] == c) for c in CLASSES} for s in names}
    report = {"found": n, "kept": len(keep), "removed_duplicates": removed_dups,
              "cross_class_conflicts_dropped": len(conflicts), "counts": counts,
              "leakage_check": "groups never span splits"}
    # verify no group/cluster spans splits
    span = defaultdict(set)
    for k in keep: span[uf.f(k)].add(split_of[k])
    assert all(len(v) == 1 for v in span.values()), "LEAKAGE: a cluster spans splits"
    with open(os.path.join(a.out, "split_report.json"), "w") as f: json.dump(report, f, indent=2)
    if conflicts:
        with open(os.path.join(a.out, "label_conflicts.txt"), "w") as f:
            for x, y in conflicts: f.write(f"{x}  <->  {y}\n")
    print(json.dumps(report, indent=2))
    for s in names:
        for c in CLASSES:
            if counts[s][c] < 20: print(f"[warn] only {counts[s][c]} images in {s}/{c}")


if __name__ == "__main__":
    main()