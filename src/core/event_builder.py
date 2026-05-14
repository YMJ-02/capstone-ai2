"""MQTT 메시지 봉투(envelope) 빌더. OUTPUT_SCHEMA v1.1 공통 헤더를 평탄 병합한다."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.config import node_cfg

KST = timezone(timedelta(hours=9))


def now_unix() -> float:
    return time.time()


def now_iso_kst() -> str:
    return datetime.fromtimestamp(now_unix(), tz=KST).isoformat(timespec="milliseconds")


def build_envelope(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    envelope: Dict[str, Any] = {
        "schema_version": node_cfg.schema_version,
        "event_type": event_type,
        "occurred_at": now_iso_kst(),
        "occurred_at_unix": now_unix(),
        "node_id": node_cfg.node_id,
    }
    envelope.update(payload)
    return envelope
