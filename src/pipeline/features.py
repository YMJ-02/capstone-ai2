"""자세 좌표 → 낙상 판정용 특징 벡터.

MediaPipe Pose 좌표계: x∈[0,1] 좌→우, y∈[0,1] 상→하.
y가 커질수록 화면 아래쪽이므로 "낙하"는 hip_center_y 증가로 나타난다.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.config import rule_cfg
from src.io.zmq_subscriber import PoseFrame

log = logging.getLogger(__name__)

LM_LEFT_SHOULDER = 11
LM_RIGHT_SHOULDER = 12
LM_LEFT_HIP = 23
LM_RIGHT_HIP = 24


@dataclass(frozen=True)
class Features:
    frame_id: int
    timestamp: float
    hip_center_x: float
    hip_center_y: float
    shoulder_center_x: float
    shoulder_center_y: float
    torso_angle_deg: float
    bbox_width: float
    bbox_height: float
    bbox_aspect: float


def _lm(landmarks: List[dict], idx: int) -> dict:
    if idx < len(landmarks) and landmarks[idx].get("id") == idx:
        return landmarks[idx]
    for lm in landmarks:
        if lm.get("id") == idx:
            return lm
    raise KeyError(f"landmark id={idx} not found")


def _center(a: dict, b: dict) -> Tuple[float, float]:
    return ((a["x"] + b["x"]) / 2.0, (a["y"] + b["y"]) / 2.0)


def _torso_angle_deg(sc_x: float, sc_y: float, hc_x: float, hc_y: float) -> float:
    """수직축(아래방향) 기준 토르소 각도. 0=직립, 90=수평, 180=거꾸로."""
    dx = hc_x - sc_x
    dy = hc_y - sc_y
    norm = math.hypot(dx, dy)
    if norm < 1e-6:
        return 0.0
    cos_a = max(-1.0, min(1.0, dy / norm))
    return math.degrees(math.acos(cos_a))


def extract(frame: PoseFrame, vis_thresh: Optional[float] = None) -> Optional[Features]:
    """프레임 → Features. 핵심 4개 랜드마크(어깨/엉덩이) 가시성 미달이면 None."""
    if vis_thresh is None:
        vis_thresh = rule_cfg.landmark_visibility_thresh

    try:
        ls = _lm(frame.landmarks, LM_LEFT_SHOULDER)
        rs = _lm(frame.landmarks, LM_RIGHT_SHOULDER)
        lh = _lm(frame.landmarks, LM_LEFT_HIP)
        rh = _lm(frame.landmarks, LM_RIGHT_HIP)
    except KeyError as e:
        log.debug("frame=%d landmark missing: %s", frame.frame_id, e)
        return None

    vs = [p.get("v", 0.0) for p in (ls, rs, lh, rh)]
    if not all(v >= vis_thresh for v in vs):
        log.debug(
            "frame=%d visibility miss: ls=%.2f rs=%.2f lh=%.2f rh=%.2f (thresh=%.2f)",
            frame.frame_id, *vs, vis_thresh,
        )
        return None

    sc_x, sc_y = _center(ls, rs)
    hc_x, hc_y = _center(lh, rh)
    torso = _torso_angle_deg(sc_x, sc_y, hc_x, hc_y)

    visible = [lm for lm in frame.landmarks if lm.get("v", 0.0) >= vis_thresh]
    if visible:
        xs = [lm["x"] for lm in visible]
        ys = [lm["y"] for lm in visible]
        bbox_w = max(xs) - min(xs)
        bbox_h = max(ys) - min(ys)
    else:
        bbox_w = bbox_h = 0.0
    bbox_aspect = bbox_w / bbox_h if bbox_h > 1e-6 else 0.0

    return Features(
        frame_id=frame.frame_id,
        timestamp=frame.timestamp,
        hip_center_x=hc_x,
        hip_center_y=hc_y,
        shoulder_center_x=sc_x,
        shoulder_center_y=sc_y,
        torso_angle_deg=torso,
        bbox_width=bbox_w,
        bbox_height=bbox_h,
        bbox_aspect=bbox_aspect,
    )
