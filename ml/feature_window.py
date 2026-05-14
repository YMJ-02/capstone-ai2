"""학습/추론 공통 feature window 정의.

CNN 입력: 최근 N 프레임의 [torso_angle, vert_extent, bbox_aspect, hip_y, hip_velocity]
형태로 (N, 5) 텐서를 만든다. 정규화 방식과 채널 순서를 한 곳에 모아두어
학습-추론 간 mismatch를 방지한다.
"""
from __future__ import annotations

from typing import Iterable, List

import numpy as np

WINDOW_LEN = 30   # 3초 @ 10fps
N_FEATURES = 5

CH_TORSO = 0
CH_VERT = 1
CH_ASPECT = 2
CH_HIP_Y = 3
CH_HIP_VEL = 4


def normalize_row(
    torso_deg: float,
    vert_extent: float,
    bbox_aspect: float,
    hip_y: float,
    hip_velocity: float,
) -> List[float]:
    """단일 프레임의 5채널을 [0,1] 부근으로 정규화."""
    return [
        max(0.0, min(1.0, torso_deg / 180.0)),
        max(0.0, min(1.0, vert_extent / 0.5)),
        max(0.0, min(1.0, bbox_aspect / 3.0)),
        max(0.0, min(1.5, hip_y)) / 1.5,
        # velocity는 -5~5 가정, sigmoid 변환으로 [0,1]에 매핑 (0 → 0.5, +대 → 1, -대 → 0)
        1.0 / (1.0 + np.exp(-hip_velocity)),
    ]


def build_window(rows: Iterable[List[float]]) -> np.ndarray:
    """길이 N 이하의 row 리스트를 (WINDOW_LEN, N_FEATURES) 배열로. 부족하면 앞쪽을 0으로 패딩."""
    rows = list(rows)
    if len(rows) >= WINDOW_LEN:
        used = rows[-WINDOW_LEN:]
    else:
        pad = [[0.0] * N_FEATURES] * (WINDOW_LEN - len(rows))
        used = pad + rows
    return np.asarray(used, dtype=np.float32)
