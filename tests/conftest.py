"""테스트 헬퍼: 합성 PoseFrame 생성.

신체 축(어깨→엉덩이)을 기준으로 머리/무릎/발목을 실제 비율로 배치하고
체축 직교 방향으로 ±0.05 두께를 두어 bbox가 의미있는 너비/높이를 가지도록 한다.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from src.io.zmq_subscriber import PoseFrame


def _along(sh_x: float, sh_y: float, hp_x: float, hp_y: float, t: float) -> Tuple[float, float]:
    """어깨 기준 체축 방향으로 t 만큼 이동한 위치 (t<0: 머리쪽, t>1: 발쪽)."""
    return sh_x + (hp_x - sh_x) * t, sh_y + (hp_y - sh_y) * t


def _perp_offset(sh_x: float, sh_y: float, hp_x: float, hp_y: float, w: float) -> Tuple[float, float]:
    dx, dy = hp_x - sh_x, hp_y - sh_y
    norm = math.hypot(dx, dy) or 1e-6
    return -dy / norm * w, dx / norm * w


def make_frame(
    frame_id: int,
    ts: float,
    sh_x: float,
    sh_y: float,
    hp_x: float,
    hp_y: float,
    visibility: float = 0.9,
) -> PoseFrame:
    px, py = _perp_offset(sh_x, sh_y, hp_x, hp_y, 0.05)
    head_x, head_y = _along(sh_x, sh_y, hp_x, hp_y, -0.75)
    knee_x, knee_y = _along(sh_x, sh_y, hp_x, hp_y, 2.0)
    ankle_x, ankle_y = _along(sh_x, sh_y, hp_x, hp_y, 2.75)

    lms: List[dict] = []
    for i in range(33):
        if i == 0:
            x, y = head_x, head_y
        elif i == 11:
            x, y = sh_x - px, sh_y - py
        elif i == 12:
            x, y = sh_x + px, sh_y + py
        elif i == 23:
            x, y = hp_x - px, hp_y - py
        elif i == 24:
            x, y = hp_x + px, hp_y + py
        elif i == 25:
            x, y = knee_x - px, knee_y - py
        elif i == 26:
            x, y = knee_x + px, knee_y + py
        elif i == 27:
            x, y = ankle_x - px, ankle_y - py
        elif i == 28:
            x, y = ankle_x + px, ankle_y + py
        else:
            x, y = (sh_x + hp_x) / 2.0, (sh_y + hp_y) / 2.0
        lms.append({"id": i, "x": x, "y": y, "z": 0.0, "v": visibility})
    return PoseFrame(
        node_id="test",
        frame_id=frame_id,
        timestamp=ts,
        image_size=(640, 480),
        landmarks=lms,
    )
