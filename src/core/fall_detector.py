"""파이프라인 오케스트레이션: PoseFrame → Features → RuleGate → FallEvent.

Phase 2: 규칙 게이트 단독.
Phase 3: 의심(suspected) 시 CNN 호출하여 confidence 융합 예정.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.config import node_cfg
from src.io.zmq_subscriber import PoseFrame
from src.pipeline.features import Features, extract
from src.pipeline.rule_gate import FallTrigger, RuleGate

log = logging.getLogger(__name__)


@dataclass
class FallEvent:
    confidence: float
    last_features: Features
    rule_debug: dict


class FallDetector:
    def __init__(self) -> None:
        self.gate = RuleGate()

    def update(self, frame: PoseFrame) -> Optional[FallEvent]:
        feats = extract(frame)
        if feats is None:
            return None
        trig: FallTrigger = self.gate.update(feats)
        if trig.confirmed:
            return FallEvent(
                confidence=trig.confidence,
                last_features=feats,
                rule_debug=trig.debug,
            )
        return None


def build_fall_payload(event: FallEvent) -> dict:
    """OUTPUT_SCHEMA v1.1 fall_detected payload (envelope는 publisher가 덧붙임)."""
    conf = event.confidence
    pct = int(round(conf * 100))
    ts = int(event.last_features.timestamp)
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
            "method": "rule_based",
            "action": "fall",
            "action_confidence": round(conf, 3),
        },
        "debug": event.rule_debug,
    }
