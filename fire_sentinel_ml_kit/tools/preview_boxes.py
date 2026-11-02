r"""
tools/preview_boxes.py — see what each class id in a YOLO dataset actually looks like.
Writes a few example images per class with that class's boxes drawn on them, so you can open the
folder and tell which class is the flame (needed when data.yaml only has names like '0' and '1').

    python tools\preview_boxes.py --source "ml/yolo/sources/Fire detection.v1i.yolov8" --n 6
Output: ml\yolo\preview\<dataset>\class<ID>_<name>_<k>.jpg   (boxes drawn in red with the class id)
"""
import argparse, os, random, re
import yaml
from PIL import Image, ImageDraw

EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COL = ["red", "cyan", "yellow", "lime", "magenta"]


def boxes_of(lbl):
    out = []
    for line in open(lbl, encoding="utf-8"):
        p = line.split()
        if len(p) < 5: continue
        try: c = int(float(p[0])); v = [float(x) for x in p[1:]]
        except ValueError: continue
        if len(v) == 4: cx, cy, w, h = v
        else:
            xs, ys = v[0::2], v[1::2]
            cx, cy, w, h = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)
        out.append((c, cx, cy, w, h))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default="ml/yolo/preview")
    a = ap.parse_args()
    d = yaml.safe_load(open(os.path.join(a.source, "data.yaml"), encoding="utf-8"))
    names = d["names"]; names = [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)
    per = {i: [] for i in range(len(names))}
    for s in ("train", "valid", "val", "test"):
        idir, ldir = os.path.join(a.source, s, "images"), os.path.join(a.source, s, "labels")
        if not os.path.isdir(idir): continue
        for fn in os.listdir(idir):
            if os.path.splitext(fn)[1].lower() not in EXT: continue
            lp = os.path.join(ldir, os.path.splitext(fn)[0] + ".txt")
            if not os.path.exists(lp): continue
            for c in {b[0] for b in boxes_of(lp)}:
                if c in per: per[c].append((os.path.join(idir, fn), lp))
    od = os.path.join(a.out, re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(os.path.normpath(a.source))))
    os.makedirs(od, exist_ok=True)
    rng = random.Random(0)
    for c, lst in per.items():
        picks = rng.sample(lst, min(a.n, len(lst)))
        print(f"class {c} ('{names[c]}'): {len(lst)} images with this class, saved {len(picks)} previews")
        for k, (ip, lp) in enumerate(picks):
            im = Image.open(ip).convert("RGB"); W, H = im.size; dr = ImageDraw.Draw(im)
            for cc, cx, cy, w, h in boxes_of(lp):
                if cc != c: continue
                dr.rectangle([(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H], outline=COL[c % len(COL)], width=max(2, W // 160))
                dr.text(((cx - w / 2) * W + 3, (cy - h / 2) * H + 3), f"class {c}", fill=COL[c % len(COL)])
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(names[c]))
            im.save(os.path.join(od, f"class{c}_{safe}_{k}.jpg"))
    print("open this folder and look:", os.path.abspath(od))


if __name__ == "__main__":
    main()