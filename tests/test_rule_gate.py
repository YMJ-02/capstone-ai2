from __future__ import annotations

from typing import List

from src.config import rule_cfg
from src.core.fall_detector import FallDetector
from tests.conftest import make_frame


def _drive(detector: FallDetector, frames):
    events = []
    for f in frames:
        e = detector.update(f)
        if e is not None:
            events.append(e)
    return events


def _stable_sequence(t0: float, n: int, dt: float = 0.1) -> List:
    return [
        make_frame(i, t0 + i * dt, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5)
        for i in range(n)
    ]


def _fall_sequence(t0: float) -> List:
    """직립 → 0.3초 만에 hip_y 0.5→0.85로 하강 → 가로 자세로 1초 정지."""
    frames = _stable_sequence(t0, 10)  # 1초 직립

    # 급강하 3프레임 (0.3초 동안 hip_y 0.55→0.85)
    drop_t0 = t0 + 1.0
    drop_y = [0.55, 0.7, 0.85]
    for k, hy in enumerate(drop_y):
        frames.append(make_frame(10 + k, drop_t0 + (k + 1) * 0.1,
                                 sh_x=0.5, sh_y=0.3 + 0.05 * k, hp_x=0.5, hp_y=hy))

    # 수평 자세 정지 (1초)
    lie_t0 = drop_t0 + 0.4
    for k in range(10):
        frames.append(make_frame(13 + k, lie_t0 + k * 0.1,
                                 sh_x=0.3, sh_y=0.85, hp_x=0.7, hp_y=0.85))
    return frames


def test_stable_pose_produces_no_event():
    det = FallDetector()
    events = _drive(det, _stable_sequence(t0=1000.0, n=50))
    assert events == []


def test_fall_sequence_produces_confirmed_event():
    det = FallDetector()
    events = _drive(det, _fall_sequence(t0=2000.0))
    assert len(events) >= 1
    e = events[0]
    assert e.confidence > 0.5
    assert e.last_features.torso_angle_deg > rule_cfg.torso_angle_horizontal_deg
    assert e.last_features.hip_center_y > rule_cfg.hip_y_low_thresh


def test_cooldown_blocks_second_fall():
    det = FallDetector()
    # 첫 낙상
    _drive(det, _fall_sequence(t0=3000.0))
    # 쿨다운 내 즉시 두 번째 낙상 시퀀스
    second = _fall_sequence(t0=3003.0)  # cooldown 5초 < 두 번째 시작
    events = _drive(det, second)
    assert events == []
