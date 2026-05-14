"""규칙 기반 낙상 1차 게이트. 상태머신: NORMAL → DESCENDING → FALLEN.

핵심 신호:
    - torso_angle_deg: 직립 0°, 수평 90° (가장 강한 누움 지표)
    - torso_vertical_extent: shoulder-hip y차이. 직립 ~0.25, 누움 ~0.05
    - bbox_aspect: 직립 < 1, 누움 > 1
    - hip_velocity: hip_y 변화율, 양수=하강

이전 버전은 hip_y 절대값(>0.65)에 의존했으나 카메라 각도에 따라 누워도
hip_y가 작아지는 경우가 있어 제거했다. 신체 자세 자체(각도, 수직범위, 가로비)로 판정.

상태 전이:
    NORMAL → DESCENDING:
        ① hip 하강 속도가 임계 초과, 또는
        ② 이미 수평 자세 감지 (직접 진입 — 카메라 가동 직후 이미 누워있는 케이스)
    DESCENDING → FALLEN: 수평 자세 + 작은 수직범위 + 가로 bbox 만족
    DESCENDING → NORMAL: timeout 또는 직립 복귀
    FALLEN: 정지(stillness) 확인되면 낙상 확정 → 이벤트 발행, 그 후 cooldown
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Deque

from src.config import rule_cfg
from src.pipeline.features import Features

log = logging.getLogger(__name__)


class State(Enum):
    NORMAL = auto()
    DESCENDING = auto()
    FALLEN = auto()


@dataclass(frozen=True)
class FallTrigger:
    suspected: bool
    confirmed: bool
    confidence: float
    debug: dict


class RuleGate:
    def __init__(self) -> None:
        self.state: State = State.NORMAL
        self._history: Deque[Features] = deque(maxlen=rule_cfg.window_size)
        self._state_entered_at: float = 0.0
        self._last_fall_at: float = 0.0
        self._last_seen_ts: float = -1.0
        # FALLEN 상태에서 non-horizontal 연속 시작 시각. 0이면 streak 없음.
        self._non_horizontal_streak_start: float = 0.0

    @property
    def history(self) -> Deque[Features]:
        return self._history

    def update(self, f: Features) -> FallTrigger:
        # vision-pi가 같은 frame을 재발행하거나 timestamp가 멈춘 경우 무시.
        # 이 경우 elapsed가 진행 안 되어 DESCENDING에 갇히는 현상이 있었다.
        if self._last_seen_ts > 0 and f.timestamp <= self._last_seen_ts:
            log.debug(
                "frame=%d stale timestamp %.3f <= last %.3f — skipped",
                f.frame_id, f.timestamp, self._last_seen_ts,
            )
            return FallTrigger(False, False, 0.0, {"state": self.state.name, "stale": True})
        self._last_seen_ts = f.timestamp

        self._history.append(f)
        vel = self._hip_velocity()
        horizontal = self._is_horizontal(f)
        debug = {
            "state": self.state.name,
            "torso_deg": round(f.torso_angle_deg, 1),
            "hip_y": round(f.hip_center_y, 3),
            "bbox_aspect": round(f.bbox_aspect, 2),
            "vert_extent": round(f.torso_vertical_extent, 3),
            "hip_velocity": round(vel, 3),
            "horizontal": horizontal,
        }
        log.debug(
            "frame=%d state=%s torso=%.1f vert=%.3f aspect=%.2f vel=%.3f horiz=%s",
            f.frame_id, self.state.name,
            f.torso_angle_deg, f.torso_vertical_extent, f.bbox_aspect, vel, horizontal,
        )

        if (f.timestamp - self._last_fall_at) < rule_cfg.fall_cooldown_sec and self._last_fall_at > 0:
            return FallTrigger(False, False, 0.0, debug)

        if self.state is State.NORMAL:
            # ① 급강하 감지 → DESCENDING
            if vel > rule_cfg.hip_drop_velocity_thresh:
                self._transition(State.DESCENDING, f.timestamp, f)
                conf = min(0.5 + (vel - rule_cfg.hip_drop_velocity_thresh) * 0.3, 0.9)
                return FallTrigger(True, False, conf, debug)
            # ② 이미 수평 자세 감지 → DESCENDING 직진입
            #    (카메라 시작 직후 이미 누워있는 케이스. stillness 거쳐 FALLEN으로 확정)
            if horizontal:
                self._transition(State.DESCENDING, f.timestamp, f)
                return FallTrigger(True, False, 0.5, debug)
            return FallTrigger(False, False, 0.0, debug)

        if self.state is State.DESCENDING:
            elapsed = f.timestamp - self._state_entered_at
            debug["elapsed_sec"] = round(elapsed, 2)
            # 직립 복귀 (수직 자세 회복) → 즉시 NORMAL
            if self._is_clearly_upright(f):
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(False, False, 0.0, debug)
            if elapsed > rule_cfg.descending_to_fallen_timeout_sec:
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(False, False, 0.0, debug)
            if horizontal:
                self._transition(State.FALLEN, f.timestamp, f)
                return FallTrigger(True, False, self._rule_confidence(f), debug)
            return FallTrigger(True, False, 0.0, debug)

        if self.state is State.FALLEN:
            elapsed_in_fallen = f.timestamp - self._state_entered_at
            debug["elapsed_fallen"] = round(elapsed_in_fallen, 2)

            # non-horizontal streak 추적: 한 프레임 노이즈로 즉시 탈출 방지.
            if not horizontal:
                if self._non_horizontal_streak_start == 0.0:
                    self._non_horizontal_streak_start = f.timestamp
            else:
                self._non_horizontal_streak_start = 0.0

            # ① 빠른 확정: stillness 통과
            if self._is_still(f):
                conf = self._rule_confidence(f)
                self._last_fall_at = f.timestamp
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(True, True, conf, debug)

            # ② 시간 기반 확정: N초 이상 누워있음 (stillness 못 잡는 의식 있는 낙상 대응)
            if elapsed_in_fallen >= rule_cfg.fallen_confirm_timeout_sec:
                conf = self._rule_confidence(f)
                self._last_fall_at = f.timestamp
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(True, True, conf, debug)

            # ③ 탈출: non-horizontal이 지속 시간 이상 유지된 경우만
            if (
                self._non_horizontal_streak_start > 0
                and f.timestamp - self._non_horizontal_streak_start
                >= rule_cfg.fallen_exit_sustain_sec
            ):
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(False, False, 0.0, debug)

            return FallTrigger(True, False, 0.0, debug)

        return FallTrigger(False, False, 0.0, debug)

    def _is_horizontal(self, f: Features) -> bool:
        """수평 자세 판정. torso_angle이 핵심이고, vertical_extent와 aspect를 보조 신호로.

        세 신호 중 2개 이상 만족 시 horizontal로 본다 (단일 신호 잡음에 강함).
        """
        signals = (
            f.torso_angle_deg > rule_cfg.torso_angle_horizontal_deg,
            f.torso_vertical_extent < rule_cfg.torso_vertical_extent_thresh,
            f.bbox_aspect > rule_cfg.bbox_aspect_ratio_thresh,
        )
        return sum(signals) >= 2

    def _is_clearly_upright(self, f: Features) -> bool:
        """완전한 직립 자세. DESCENDING에서 빠르게 NORMAL로 빠지는 조건."""
        return (
            f.torso_angle_deg < 20.0
            and f.torso_vertical_extent > rule_cfg.torso_vertical_extent_thresh * 1.5
            and f.bbox_aspect < 0.7
        )

    def _transition(self, to: State, t: float, f: Features) -> None:
        if self.state is not to:
            log.info(
                "rule_gate: %s → %s  torso=%.1f° vert=%.2f aspect=%.2f vel=%.2f",
                self.state.name, to.name,
                f.torso_angle_deg, f.torso_vertical_extent, f.bbox_aspect,
                self._hip_velocity(),
            )
        self.state = to
        self._state_entered_at = t
        self._non_horizontal_streak_start = 0.0

    def _hip_velocity(self) -> float:
        """가장 최근 두 프레임 사이의 hip_y 변화율 (1/sec). 양수=하강."""
        if len(self._history) < 2:
            return 0.0
        prev = self._history[-2]
        cur = self._history[-1]
        dt = cur.timestamp - prev.timestamp
        if dt <= 0:
            return 0.0
        return (cur.hip_center_y - prev.hip_center_y) / dt

    def _is_still(self, cur: Features) -> bool:
        cutoff = cur.timestamp - rule_cfg.stillness_window_sec
        recent = [h for h in self._history if h.timestamp >= cutoff]
        if len(recent) < 2:
            return False
        xs = [h.hip_center_x for h in recent]
        ys = [h.hip_center_y for h in recent]
        motion = (max(xs) - min(xs)) + (max(ys) - min(ys))
        return motion < rule_cfg.stillness_motion_thresh

    def _rule_confidence(self, f: Features) -> float:
        c = 0.5
        c += min(0.2, max(0.0, (f.torso_angle_deg - rule_cfg.torso_angle_horizontal_deg) / 100.0))
        c += min(0.15, max(0.0, (rule_cfg.torso_vertical_extent_thresh - f.torso_vertical_extent) * 2.0))
        c += min(0.15, max(0.0, (f.bbox_aspect - rule_cfg.bbox_aspect_ratio_thresh) * 0.2))
        return max(0.0, min(0.95, c))
