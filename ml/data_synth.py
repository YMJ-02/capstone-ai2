"""낙상/비낙상 시퀀스 합성기.

실제 라벨된 데이터셋이 없는 capstone 단계에서 1D-CNN을 학습하기 위해
규칙 기반 시뮬레이션으로 feature window를 생성한다. rule_gate가 정확히
판정하는 케이스와 헷갈리는 케이스(짧은 쭈그림, 빠른 앉기 등)를 의도적으로
섞어 CNN이 그 차이를 학습하도록 한다.

채널 순서/정규화는 ml.feature_window.normalize_row와 동일해야 한다.
"""
from __future__ import annotations

import math
import random
from typing import List, Tuple

import numpy as np

from ml.feature_window import N_FEATURES, WINDOW_LEN, normalize_row


def _row_from_pose(
    sh_y: float, hip_y: float, sh_x: float, hip_x: float,
    prev_hip_y: float, dt: float = 0.1,
) -> Tuple[List[float], float]:
    """간단한 포즈 → 정규화 5채널 row + 다음 호출용 hip_y."""
    dx = hip_x - sh_x
    dy = hip_y - sh_y
    norm = math.hypot(dx, dy) or 1e-6
    cos_a = max(-1.0, min(1.0, dy / norm))
    torso = math.degrees(math.acos(cos_a))
    vert_extent = abs(hip_y - sh_y)
    # 거친 bbox 근사: 어깨-엉덩이의 가로 거리 + 약간의 두께
    bbox_w = abs(hip_x - sh_x) + 0.1
    bbox_h = abs(hip_y - sh_y) + 0.2
    aspect = bbox_w / max(bbox_h, 1e-6)
    hip_vel = (hip_y - prev_hip_y) / dt
    row = normalize_row(torso, vert_extent, aspect, hip_y, hip_vel)
    return row, hip_y


def _noise(s: float) -> float:
    return random.uniform(-s, s)


def gen_stable() -> np.ndarray:
    """직립 정지 (label 0). hip_y ~ 0.5, shoulder 위쪽."""
    rows: List[List[float]] = []
    base_hip = random.uniform(0.4, 0.6)
    prev = base_hip
    for _ in range(WINDOW_LEN):
        hip_y = base_hip + _noise(0.01)
        sh_y = hip_y - 0.25 + _noise(0.01)
        sh_x = 0.5 + _noise(0.01)
        hip_x = 0.5 + _noise(0.01)
        row, prev = _row_from_pose(sh_y, hip_y, sh_x, hip_x, prev)
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def gen_walking() -> np.ndarray:
    """걷는 듯한 흔들림 (label 0). hip_y/x 모두 작게 진동."""
    rows: List[List[float]] = []
    base_hip = random.uniform(0.4, 0.6)
    prev = base_hip
    phase = random.uniform(0, math.tau)
    for k in range(WINDOW_LEN):
        hip_y = base_hip + 0.03 * math.sin(phase + k * 0.4) + _noise(0.01)
        sh_y = hip_y - 0.25 + _noise(0.01)
        sh_x = 0.5 + 0.05 * math.sin(phase + k * 0.4 + 1.2)
        hip_x = 0.5 + 0.05 * math.sin(phase + k * 0.4)
        row, prev = _row_from_pose(sh_y, hip_y, sh_x, hip_x, prev)
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def gen_quick_squat() -> np.ndarray:
    """빠른 앉기/쭈그림 — 누운 자세 아님 (label 0, 헷갈리는 케이스)."""
    rows: List[List[float]] = []
    prev = 0.5
    drop_start = random.randint(5, 15)
    rise_start = drop_start + random.randint(3, 6)
    for k in range(WINDOW_LEN):
        if k < drop_start:
            hip_y, sh_y = 0.5 + _noise(0.01), 0.25 + _noise(0.01)
        elif k < rise_start:
            t = (k - drop_start) / max(1, rise_start - drop_start)
            hip_y = 0.5 + 0.2 * t + _noise(0.01)
            sh_y = 0.25 + 0.15 * t + _noise(0.01)  # 어깨도 따라 내려가지만 vert_extent 유지
        else:
            hip_y, sh_y = 0.5 + _noise(0.01), 0.25 + _noise(0.01)
        sh_x = 0.5 + _noise(0.02)
        hip_x = 0.5 + _noise(0.02)
        row, prev = _row_from_pose(sh_y, hip_y, sh_x, hip_x, prev)
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def gen_fall() -> np.ndarray:
    """직립 → 급강하 → 수평 누움 (label 1)."""
    rows: List[List[float]] = []
    prev = 0.5
    drop_start = random.randint(5, 15)
    drop_dur = random.randint(2, 4)
    final_hip_y = random.uniform(0.6, 0.9)
    # 수평 누움 시 어깨/엉덩이 y가 거의 같고 x 차이가 크다
    lying_sh_y_offset = random.uniform(-0.05, 0.05)
    sh_offset_x = random.uniform(0.25, 0.4) * random.choice([-1, 1])
    for k in range(WINDOW_LEN):
        if k < drop_start:
            hip_y = 0.5 + _noise(0.01)
            sh_y = 0.25 + _noise(0.01)
            sh_x = 0.5 + _noise(0.02)
            hip_x = 0.5 + _noise(0.02)
        elif k < drop_start + drop_dur:
            t = (k - drop_start + 1) / drop_dur
            hip_y = 0.5 + (final_hip_y - 0.5) * t
            sh_y = 0.25 + (final_hip_y + lying_sh_y_offset - 0.25) * t
            sh_x = 0.5 + (0.5 + sh_offset_x - 0.5) * t
            hip_x = 0.5 + (0.5 - sh_offset_x - 0.5) * t
        else:
            hip_y = final_hip_y + _noise(0.02)
            sh_y = final_hip_y + lying_sh_y_offset + _noise(0.02)
            sh_x = 0.5 + sh_offset_x + _noise(0.03)  # 누워있어도 살짝 움직임
            hip_x = 0.5 - sh_offset_x + _noise(0.03)
        row, prev = _row_from_pose(sh_y, hip_y, sh_x, hip_x, prev)
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def gen_already_lying() -> np.ndarray:
    """카메라 켰을 때 이미 누워있음 (label 1)."""
    rows: List[List[float]] = []
    prev = random.uniform(0.6, 0.9)
    base_hip = prev
    base_sh = base_hip + random.uniform(-0.05, 0.05)
    sh_offset_x = random.uniform(0.2, 0.4) * random.choice([-1, 1])
    for _ in range(WINDOW_LEN):
        hip_y = base_hip + _noise(0.02)
        sh_y = base_sh + _noise(0.02)
        sh_x = 0.5 + sh_offset_x + _noise(0.03)
        hip_x = 0.5 - sh_offset_x + _noise(0.03)
        row, prev = _row_from_pose(sh_y, hip_y, sh_x, hip_x, prev)
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def gen_fall_then_struggle() -> np.ndarray:
    """낙상 후 일어나려 발버둥 (label 1, stillness 못 잡는 케이스)."""
    rows: List[List[float]] = []
    prev = 0.5
    drop_end = random.randint(6, 10)
    final_hip_y = random.uniform(0.6, 0.85)
    sh_offset_x = random.uniform(0.25, 0.4) * random.choice([-1, 1])
    for k in range(WINDOW_LEN):
        if k < drop_end:
            t = k / drop_end
            hip_y = 0.5 + (final_hip_y - 0.5) * t
            sh_y = 0.25 + (final_hip_y - 0.25) * t
            sh_x = 0.5 + sh_offset_x * t
            hip_x = 0.5 - sh_offset_x * t
        else:
            # 큰 움직임이지만 자세 자체는 horizontal
            hip_y = final_hip_y + 0.05 * math.sin(k * 0.7) + _noise(0.02)
            sh_y = final_hip_y + _noise(0.03)
            sh_x = 0.5 + sh_offset_x + 0.08 * math.sin(k * 0.5)
            hip_x = 0.5 - sh_offset_x + 0.08 * math.sin(k * 0.5 + 1)
        row, prev = _row_from_pose(sh_y, hip_y, sh_x, hip_x, prev)
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


NEG_GENERATORS = [gen_stable, gen_walking, gen_quick_squat]
POS_GENERATORS = [gen_fall, gen_already_lying, gen_fall_then_struggle]


def make_dataset(
    n_per_class: int = 4000, seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray]:
    """(N*2, WINDOW_LEN, N_FEATURES), (N*2,) 라벨 반환."""
    random.seed(seed)
    np.random.seed(seed)
    xs: List[np.ndarray] = []
    ys: List[int] = []
    for _ in range(n_per_class):
        xs.append(random.choice(NEG_GENERATORS)())
        ys.append(0)
    for _ in range(n_per_class):
        xs.append(random.choice(POS_GENERATORS)())
        ys.append(1)
    X = np.stack(xs).astype(np.float32)
    y = np.asarray(ys, dtype=np.float32)
    # shuffle
    idx = np.arange(len(X))
    np.random.shuffle(idx)
    return X[idx], y[idx]


if __name__ == "__main__":
    X, y = make_dataset(n_per_class=10)
    print("X shape:", X.shape, "y shape:", y.shape)
    print("X[0]:\n", X[0])
    print("y[:10]:", y[:10])
