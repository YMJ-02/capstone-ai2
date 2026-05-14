"""capstone-app(Flutter) 통합용 페이로드 변환기.

앱이 기대하는 매-프레임 WebSocket 페이로드:
    {
        "timestamp": int (unix seconds),
        "fall_prob": float [0.0, 1.0],
        "status": "NORMAL" | "WARNING" | "FALL",
        "pose_data": [
            {"x": float, "y": float, "z": float, "visibility": float},
            ...
        ],   # length=33, MediaPipe Pose 순서
        "video_clip_url": null,  # 본 노드에서는 영상 미지원
    }

설계 노트:
- 우리 rule_gate의 State (NORMAL/DESCENDING/FALLEN) → 앱의 status 매핑
- fall_prob는 매 frame 보내는 연속 신호. confirmed 이벤트와는 다른 채널.
- pose_data는 vision-pi가 보낸 33-landmark를 앱 형식으로 변환 (id 제외, v→visibility).
- 영상은 별도 시스템 책임 (본 노드 범위 밖).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.config import app_cfg
from src.io.zmq_subscriber import PoseFrame
from src.pipeline.features import Features
from src.pipeline.rule_gate import State


_STATE_TO_STATUS = {
    State.NORMAL: "NORMAL",
    State.DESCENDING: "WARNING",
    State.FALLEN: "FALL",
}


@dataclass(frozen=True)
class AppFrame:
    """매 frame WS 송신용 dict 페이로드 + 부수 메타데이터."""
    payload: dict
    status: str
    fall_prob: float


def _state_to_prob(state: State, override: Optional[float]) -> float:
    """state→fall_prob 매핑. 상위에서 명시한 override가 있으면 우선 사용.

    confirmed 시점에 fused_confidence를 override로 넘기면 즉시 0.9+가 송신된다.
    그 외에는 state별 고정 prob (앱 임계 ≥0.7 FALL, ≥0.4 WARNING 와 일관).
    """
    if override is not None:
        return max(0.0, min(1.0, override))
    if state is State.FALLEN:
        return app_cfg.fall_prob
    if state is State.DESCENDING:
        return app_cfg.warning_prob
    return 0.0


def _convert_landmarks(landmarks: List[dict]) -> List[dict]:
    """vision-pi {id, x, y, z, v} → 앱 {x, y, z, visibility}. id 순서대로 정렬해 길이 33 보장.

    누락된 id가 있으면 가시성 0으로 채운다 (앱이 visibility 보고 미표시).
    """
    by_id = {int(lm.get("id", -1)): lm for lm in landmarks}
    out: List[dict] = []
    for i in range(33):
        lm = by_id.get(i)
        if lm is None:
            out.append({"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0})
        else:
            out.append({
                "x": float(lm.get("x", 0.0)),
                "y": float(lm.get("y", 0.0)),
                "z": float(lm.get("z", 0.0)),
                "visibility": float(lm.get("v", 0.0)),
            })
    return out


def build_app_frame(
    frame: PoseFrame,
    feats: Optional[Features],
    state: State,
    confirmed_confidence: Optional[float] = None,
) -> AppFrame:
    """매 frame 호출. confirmed가 발생한 frame이면 confirmed_confidence로 fall_prob override.

    feats가 None(가시성 미달)이어도 페이로드는 생성 (앱이 끊김 없이 stream 유지).
    """
    prob = _state_to_prob(state, confirmed_confidence)
    if prob >= 0.7:
        status = "FALL"
    elif prob >= 0.4:
        status = "WARNING"
    else:
        status = _STATE_TO_STATUS.get(state, "NORMAL")

    payload = {
        "timestamp": int(frame.timestamp),
        "fall_prob": round(prob, 4),
        "status": status,
        "pose_data": _convert_landmarks(frame.landmarks),
        "video_clip_url": None,
    }
    return AppFrame(payload=payload, status=status, fall_prob=prob)
