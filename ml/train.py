"""1D-CNN 학습 → Keras 저장 → TFLite 변환.

실행:
    python -m ml.train

산출물:
    models/fall_validator.keras  — 학습된 모델
    models/fall_validator.tflite — Pi 런타임용 (tflite-runtime로 추론)
    models/training_report.txt   — 학습 요약 (loss/accuracy/val_*)

CPU 환경에서도 1~2분 안에 끝나는 작은 모델/데이터셋.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import tensorflow as tf

from ml.data_synth import make_dataset
from ml.model import build_model

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--n-per-class", type=int, default=4000)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--val-split", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    MODELS_DIR.mkdir(exist_ok=True)
    tf.random.set_seed(args.seed)
    np.random.seed(args.seed)

    log.info("합성 데이터 생성 (n_per_class=%d) ...", args.n_per_class)
    X, y = make_dataset(n_per_class=args.n_per_class, seed=args.seed)
    log.info("X=%s y=%s pos_ratio=%.3f", X.shape, y.shape, y.mean())

    model = build_model()
    model.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss="binary_crossentropy",
        metrics=["accuracy", tf.keras.metrics.Precision(name="prec"),
                 tf.keras.metrics.Recall(name="rec")],
    )
    model.summary(print_fn=log.info)

    es = tf.keras.callbacks.EarlyStopping(
        patience=4, restore_best_weights=True, monitor="val_loss"
    )
    hist = model.fit(
        X, y,
        validation_split=args.val_split,
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=[es],
        verbose=2,
    )

    keras_path = MODELS_DIR / "fall_validator.keras"
    model.save(keras_path)
    log.info("Keras 저장: %s", keras_path)

    # TFLite 변환 (float32, 양자화 X — Pi에서도 충분히 빠르고 정밀도 손실 회피)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_bytes = converter.convert()
    tflite_path = MODELS_DIR / "fall_validator.tflite"
    tflite_path.write_bytes(tflite_bytes)
    log.info("TFLite 저장: %s (%d bytes)", tflite_path, len(tflite_bytes))

    # 보고서
    final_metrics = {k: float(v[-1]) for k, v in hist.history.items()}
    report = MODELS_DIR / "training_report.txt"
    with report.open("w") as f:
        f.write("=== fall_validator 1D-CNN 학습 보고 ===\n")
        f.write(f"n_per_class={args.n_per_class} epochs(real)={len(hist.history['loss'])}\n")
        f.write(f"val_split={args.val_split} batch_size={args.batch_size}\n\n")
        for k, v in final_metrics.items():
            f.write(f"{k}: {v:.4f}\n")
    log.info("보고서: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
