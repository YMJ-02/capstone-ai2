"""파이프라인 오케스트레이션: PoseFrame → Features → RuleGate (+CnnValidator) → FallEvent.

Phase 2: 규칙 게이트 단독.
Phase 3: 규칙이 의심하면 CNN 호출, confidence 융합. 모델이 없으면 규칙만으로 동작.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.config import cnn_cfg, node_cfg
from src.io.zmq_subscriber import PoseFrame
from src.pipeline.cnn_validator import CnnValidator
from src.pipeline.features import Features, extract
from src.pipeline.rule_gate import FallTrigger, RuleGate, State

log = logging.getLogger(__name__)


@dataclass
class FallEvent:
    confidence: float
    last_features: Features
    rule_debug: dict


class FallDetector:
    def __init__(self) -> None:
        self.gate = RuleGate()
        self.cnn: Optional[CnnValidator] = CnnValidator() if cnn_cfg.enabled else None

    def update(self, frame: PoseFrame) -> Optional[FallEvent]:
        feats = extract(frame)
        if feats is None:
            return None

        # CNN window는 항상 갱신 (가벼움). 추론은 의심 시점에만.
        if self.cnn is not None:
            self.cnn.observe(feats)

        trig: FallTrigger = self.gate.update(feats)

        # CNN 추론: 규칙이 의심하거나 이미 DESCENDING/FALLEN 진입한 경우에만.
        cnn_prob: Optional[float] = None
        if self.cnn is not None and self.cnn.enabled and (
            trig.suspected or self.gate.state in (State.DESCENDING, State.FALLEN)
        ):
            cnn_prob = self.cnn.predict()
            if cnn_prob is not None:
                trig.debug["cnn_prob"] = round(cnn_prob, 3)

        if trig.confirmed:
            conf = self._fuse(trig.confidence, cnn_prob)
            trig.debug["fused_confidence"] = round(conf, 3)
            return FallEvent(confidence=conf, last_features=feats, rule_debug=trig.debug)
        return None

    @staticmethod
    def _fuse(rule_conf: float, cnn_prob: Optional[float]) -> float:
        """규칙 confidence와 CNN 확률의 가중 평균. CNN 없으면 규칙값 그대로."""
        if cnn_prob is None:
            return rule_conf
        w = cnn_cfg.fusion_weight
        return max(0.0, min(0.99, (1.0 - w) * rule_conf + w * cnn_prob))


def build_fall_payload(event: FallEvent) -> dict:
    """OUTPUT_SCHEMA v1.1 fall_detected payload (envelope는 publisher가 덧붙임)."""
    conf = event.confidence
    pct = int(round(conf * 100))
    ts = int(event.last_features.timestamp)
    cnn_prob = event.rule_debug.get("cnn_prob")
    method = "rule+cnn" if cnn_prob is not None else "rule_based"
    return {
        "event_id": f"fall-{node_cfg.node_id}-{ts}",
        "severity": "critical",
        "location": {
            "node_id": node_cfg.node_id,
            "camera": node_cfg.camera_label,
            "label": node_cfg.location_label,
        },
        "confidence": round(conf, 3),
        "confidence_pct": pct,
        "message": {
            "title": "낙상 감지",
            "body": f"{node_cfg.location_label}에서 낙상이 감지되었습니다. (신뢰도 {pct}%)",
            "short": f"낙상 감지 ({pct}%)",
        },
        "ai": {
            "method": method,
            "action": "fall",
            "action_confidence": round(conf, 3),
        },
        "debug": event.rule_debug,
    }
