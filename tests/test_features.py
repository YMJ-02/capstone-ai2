from __future__ import annotations

import math

from src.pipeline.features import extract
from tests.conftest import make_frame


def test_upright_pose_has_zero_torso_angle():
    frame = make_frame(0, 0.0, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5)
    feats = extract(frame)
    assert feats is not None
    assert feats.torso_angle_deg < 5.0
    assert feats.bbox_aspect < 1.0  # 세로가 더 김


def test_horizontal_pose_has_high_torso_angle():
    # 어깨 왼쪽, 엉덩이 오른쪽 → 가로 토르소
    frame = make_frame(0, 0.0, sh_x=0.3, sh_y=0.8, hp_x=0.7, hp_y=0.8)
    feats = extract(frame)
    assert feats is not None
    assert feats.torso_angle_deg > 80.0
    assert math.isclose(feats.torso_angle_deg, 90.0, abs_tol=2.0)


def test_low_visibility_returns_none():
    frame = make_frame(0, 0.0, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5, visibility=0.1)
    assert extract(frame) is None


def test_hip_center_is_midpoint():
    frame = make_frame(0, 0.0, sh_x=0.5, sh_y=0.3, hp_x=0.6, hp_y=0.5)
    feats = extract(frame)
    assert feats is not None
    assert math.isclose(feats.hip_center_x, 0.6, abs_tol=1e-6)
    assert math.isclose(feats.hip_center_y, 0.5, abs_tol=1e-6)
