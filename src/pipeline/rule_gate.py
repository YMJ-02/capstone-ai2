"""규칙 기반 낙상 1차 게이트. 상태머신: NORMAL → DESCENDING → FALLEN.

- NORMAL: hip_y 하강 속도가 임계 초과하면 DESCENDING
- DESCENDING: 일정 시간 내에 (수평 자세 + 낮은 hip_y + 가로 bbox) 만족 시 FALLEN
- FALLEN: 정지(stillness) 확인되면 낙상 확정 → 이벤트 발행, 그 후 cooldown
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

    @property
    def history(self) -> Deque[Features]:
        return self._history

    def update(self, f: Features) -> FallTrigger:
        self._history.append(f)
        vel = self._hip_velocity()
        debug = {
            "state": self.state.name,
            "torso_deg": round(f.torso_angle_deg, 1),
            "hip_y": round(f.hip_center_y, 3),
            "bbox_aspect": round(f.bbox_aspect, 2),
            "hip_velocity": round(vel, 3),
        }
        log.debug(
            "frame=%d state=%s torso=%.1f hip_y=%.3f aspect=%.2f vel=%.3f",
            f.frame_id, self.state.name,
            f.torso_angle_deg, f.hip_center_y, f.bbox_aspect, vel,
        )

        if (f.timestamp - self._last_fall_at) < rule_cfg.fall_cooldown_sec and self._last_fall_at > 0:
            return FallTrigger(False, False, 0.0, debug)

        if self.state is State.NORMAL:
            if vel > rule_cfg.hip_drop_velocity_thresh:
                self._transition(State.DESCENDING, f.timestamp, f)
                conf = min(0.5 + (vel - rule_cfg.hip_drop_velocity_thresh) * 0.3, 0.9)
                return FallTrigger(True, False, conf, debug)
            return FallTrigger(False, False, 0.0, debug)

        if self.state is State.DESCENDING:
            elapsed = f.timestamp - self._state_entered_at
            debug["elapsed_sec"] = round(elapsed, 2)
            if elapsed > rule_cfg.descending_to_fallen_timeout_sec:
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(False, False, 0.0, debug)
            if (
                f.torso_angle_deg > rule_cfg.torso_angle_horizontal_deg
                and f.hip_center_y > rule_cfg.hip_y_low_thresh
                and f.bbox_aspect > rule_cfg.bbox_aspect_ratio_thresh
            ):
                self._transition(State.FALLEN, f.timestamp, f)
                return FallTrigger(True, False, self._rule_confidence(f), debug)
            return FallTrigger(True, False, 0.0, debug)

        if self.state is State.FALLEN:
            if self._is_still(f):
                conf = self._rule_confidence(f)
                self._last_fall_at = f.timestamp
                self._transition(State.NORMAL, f.timestamp, f)
                return FallTrigger(True, True, conf, debug)
            return FallTrigger(True, False, 0.0, debug)

        return FallTrigger(False, False, 0.0, debug)

    def _transition(self, to: State, t: float, f: Features) -> None:
        if self.state is not to:
            log.info(
                "rule_gate: %s → %s  torso=%.1f° hip_y=%.2f aspect=%.2f vel=%.2f",
                self.state.name, to.name,
                f.torso_angle_deg, f.hip_center_y, f.bbox_aspect,
                self._hip_velocity(),
            )
        self.state = to
        self._state_entered_at = t

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
        c += min(0.2, (f.torso_angle_deg - rule_cfg.torso_angle_horizontal_deg) / 100.0)
        c += min(0.15, (f.hip_center_y - rule_cfg.hip_y_low_thresh) * 0.5)
        c += min(0.15, (f.bbox_aspect - rule_cfg.bbox_aspect_ratio_thresh) * 0.2)
        return max(0.0, min(0.95, c))
