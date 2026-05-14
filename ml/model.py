"""1D-CNN 모델 정의. 경량 (~10K 파라미터) — 라즈베리파이 TFLite 추론에 적합.

입력: (WINDOW_LEN=30, N_FEATURES=5)
출력: sigmoid (P(fall))
"""
from __future__ import annotations

import tensorflow as tf

from ml.feature_window import N_FEATURES, WINDOW_LEN


def build_model() -> tf.keras.Model:
    inp = tf.keras.Input(shape=(WINDOW_LEN, N_FEATURES), name="window")
    x = tf.keras.layers.Conv1D(16, 5, padding="same", activation="relu")(inp)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.Conv1D(32, 3, padding="same", activation="relu")(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.MaxPooling1D(2)(x)
    x = tf.keras.layers.Conv1D(32, 3, padding="same", activation="relu")(x)
    x = tf.keras.layers.GlobalAveragePooling1D()(x)
    x = tf.keras.layers.Dropout(0.2)(x)
    out = tf.keras.layers.Dense(1, activation="sigmoid", name="fall_prob")(x)
    model = tf.keras.Model(inp, out, name="fall_validator_1dcnn")
    return model
