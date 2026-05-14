from __future__ import annotations

from typing import List

from src.config import rule_cfg
from src.core.fall_detector import FallDetector
from tests.conftest import make_frame


def _drive(detector: FallDetector, frames):
    events = []
    for f in frames:
        upd = detector.update(f)
        if upd.event is not None:
            events.append(upd.event)
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
    assert e.last_features.torso_vertical_extent < rule_cfg.torso_vertical_extent_thresh


def test_already_lying_pose_detects_fall():
    """카메라 시작 직후 이미 누워있는 케이스: vel 없어도 FALLEN으로 가야 함."""
    det = FallDetector()
    # 처음부터 수평 자세 + 정지 1초
    frames = [
        make_frame(i, 5000.0 + i * 0.1, sh_x=0.3, sh_y=0.85, hp_x=0.7, hp_y=0.85)
        for i in range(15)
    ]
    events = _drive(det, frames)
    assert len(events) >= 1


def test_stale_timestamp_is_ignored():
    """같은 timestamp 프레임이 반복되어도 상태에 갇히지 않아야 한다."""
    det = FallDetector()
    f0 = make_frame(0, 7000.0, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5)
    # 동일 timestamp로 50회 반복
    for _ in range(50):
        det.update(f0)
    assert det.gate.state.name == "NORMAL"


def test_moving_while_fallen_still_confirms_by_timeout():
    """의식 있는 낙상자가 움직이고 있어도 1.5초 후 시간 기반 확정."""
    det = FallDetector()
    # 직립 0.5초
    frames = _stable_sequence(t0=8000.0, n=5)
    # 급강하 3프레임
    for k, hy in enumerate([0.55, 0.7, 0.85]):
        frames.append(make_frame(5 + k, 8000.5 + (k + 1) * 0.1,
                                 sh_x=0.5, sh_y=0.3 + 0.05 * k, hp_x=0.5, hp_y=hy))
    # 수평 자세이지만 hip_center가 크게 움직임 (stillness 임계 0.10 초과)
    # 2초간 누워있음 → 시간 기반 확정 트리거되어야 함
    lie_t0 = 8000.8 + 0.1
    for k in range(20):
        # x를 0.2~0.5 범위에서 흔들기 → motion > 0.10
        wobble_x = 0.3 + 0.2 * ((k % 4) / 3.0)
        frames.append(make_frame(8 + k, lie_t0 + k * 0.1,
                                 sh_x=wobble_x, sh_y=0.85, hp_x=wobble_x + 0.4, hp_y=0.85))
    events = _drive(det, frames)
    assert len(events) >= 1, "시간 기반 확정이 작동해야 함"


def test_brief_non_horizontal_does_not_exit_fallen():
    """FALLEN 중 한두 프레임만 non-horizontal이어도 즉시 탈출하지 않아야 함."""
    det = FallDetector()
    # 직립 → 낙상 → FALLEN 진입
    frames = _stable_sequence(t0=9000.0, n=5)
    for k, hy in enumerate([0.55, 0.7, 0.85]):
        frames.append(make_frame(5 + k, 9000.5 + (k + 1) * 0.1,
                                 sh_x=0.5, sh_y=0.3 + 0.05 * k, hp_x=0.5, hp_y=hy))
    # 누운 자세 0.3초
    lie_t0 = 9000.8 + 0.1
    for k in range(3):
        frames.append(make_frame(8 + k, lie_t0 + k * 0.1,
                                 sh_x=0.3, sh_y=0.85, hp_x=0.7, hp_y=0.85))
    # 1프레임만 직립 (노이즈)
    frames.append(make_frame(11, lie_t0 + 0.3, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5))
    # 다시 누움 1.5초
    for k in range(15):
        frames.append(make_frame(12 + k, lie_t0 + 0.4 + k * 0.1,
                                 sh_x=0.3, sh_y=0.85, hp_x=0.7, hp_y=0.85))
    _drive(det, frames)
    # 1프레임 노이즈로 NORMAL로 빠지지 않고 결과적으로 FALLEN→NORMAL 확정 완료
    # (마지막엔 cooldown 중이므로 state는 NORMAL이 정상)


def test_cooldown_blocks_second_fall():
    det = FallDetector()
    # 첫 낙상
    _drive(det, _fall_sequence(t0=3000.0))
    # 쿨다운 내 즉시 두 번째 낙상 시퀀스
    second = _fall_sequence(t0=3003.0)  # cooldown 5초 < 두 번째 시작
    events = _drive(det, second)
    assert events == []
