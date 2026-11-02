"""
ml/cnn/train_cnn.py — 3-class MobileNetV2 transfer learning (Prototype 1 recipe, 3-way head).

Phase 1: frozen backbone, train head.   Phase 2: unfreeze top layers, low LR.
Rescaling to [-1,1] lives INSIDE the model, so the device feeds raw 0-255 pixels.
Augmentation is applied in the data pipeline only (not in the exported model).

    python ml/cnn/train_cnn.py --data ml/cnn/dataset/split --img 96 --alpha 0.35
"""
import argparse, os, json, time
import numpy as np
import tensorflow as tf
from cnn_common import CLASS_NAMES, HAZ, SEED, load_split, save_json

tf.keras.utils.set_random_seed(SEED)


def count_per_class(data, split="train"):
    return [len([f for f in os.listdir(os.path.join(data, split, c))]) for c in CLASS_NAMES]


def build(img, alpha, pretrained):
    inp = tf.keras.Input((img, img, 3), name="image")
    x = tf.keras.layers.Rescaling(1 / 127.5, offset=-1, name="rescale")(inp)
    base = tf.keras.applications.MobileNetV2(
        input_shape=(img, img, 3), alpha=alpha, include_top=False,
        weights="imagenet" if pretrained else None)
    x = base(x, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.3)(x)
    out = tf.keras.layers.Dense(3, activation="softmax", name="probs")(x)
    return tf.keras.Model(inp, out), base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="ml/cnn/artifacts")
    ap.add_argument("--img", type=int, default=96)
    ap.add_argument("--alpha", type=float, default=0.35)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--epochs-head", type=int, default=8)
    ap.add_argument("--epochs-ft", type=int, default=15)
    ap.add_argument("--unfreeze", type=int, default=40, help="top N backbone layers to unfreeze")
    ap.add_argument("--haz-weight", type=float, default=1.5,
                    help="extra class-weight multiplier on hazardous_fire (favours recall)")
    ap.add_argument("--interp", default="area")
    ap.add_argument("--no-pretrained", action="store_true", help="offline/smoke tests only")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    train, _ = load_split(a.data, "train", a.img, a.batch, True, a.interp)
    val, _ = load_split(a.data, "val", a.img, a.batch, False, a.interp)

    aug = tf.keras.Sequential([
        tf.keras.layers.RandomFlip("horizontal"),
        tf.keras.layers.RandomRotation(0.06),
        tf.keras.layers.RandomZoom(0.15),
        tf.keras.layers.RandomTranslation(0.08, 0.08),
        tf.keras.layers.RandomBrightness(0.25, value_range=(0, 255)),
        tf.keras.layers.RandomContrast(0.2),
    ])
    train = train.map(lambda x, y: (aug(x, training=True), y),
                      num_parallel_calls=tf.data.AUTOTUNE).prefetch(tf.data.AUTOTUNE)
    val = val.prefetch(tf.data.AUTOTUNE)

    n = np.array(count_per_class(a.data))
    cw = {i: float(n.sum() / (3 * n[i])) for i in range(3)}
    cw[HAZ] *= a.haz_weight
    print("train counts", dict(zip(CLASS_NAMES, n.tolist())), "class_weight", cw)

    model, base = build(a.img, a.alpha, not a.no_pretrained)
    base.trainable = False
    cbs = lambda: [
        tf.keras.callbacks.EarlyStopping(patience=5, restore_best_weights=True, monitor="val_loss"),
        tf.keras.callbacks.ReduceLROnPlateau(factor=0.5, patience=2, min_lr=1e-7),
    ]
    model.compile(tf.keras.optimizers.Adam(1e-3), "sparse_categorical_crossentropy", ["accuracy"])
    t0 = time.time()
    h1 = model.fit(train, validation_data=val, epochs=a.epochs_head, class_weight=cw, callbacks=cbs())

    base.trainable = True
    for l in base.layers[:-a.unfreeze]: l.trainable = False
    for l in base.layers:
        if isinstance(l, tf.keras.layers.BatchNormalization): l.trainable = False
    model.compile(tf.keras.optimizers.Adam(1e-5), "sparse_categorical_crossentropy", ["accuracy"])
    h2 = model.fit(train, validation_data=val, epochs=a.epochs_ft, class_weight=cw, callbacks=cbs())

    model.save(os.path.join(a.out, "fire_cnn.keras"))
    save_json({"class_names": CLASS_NAMES, "img": a.img, "alpha": a.alpha, "interp": a.interp,
               "train_counts": dict(zip(CLASS_NAMES, n.tolist())), "class_weight": cw,
               "pretrained": not a.no_pretrained, "train_seconds": round(time.time() - t0),
               "history": {k: [float(v) for v in h1.history[k] + h2.history[k]]
                           for k in h1.history}},
              os.path.join(a.out, "train_info.json"))
    print("saved", os.path.join(a.out, "fire_cnn.keras"))


if __name__ == "__main__":
    main()
