"""capstone-app 페이로드 변환기 단위 테스트."""
from __future__ import annotations

from src.pipeline.app_payload import build_app_frame
from src.pipeline.features import extract
from src.pipeline.rule_gate import State
from tests.conftest import make_frame


def _frame_and_feats(sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5):
    f = make_frame(0, 1735000000.5, sh_x=sh_x, sh_y=sh_y, hp_x=hp_x, hp_y=hp_y)
    return f, extract(f)


def test_normal_state_emits_zero_prob():
    f, feats = _frame_and_feats()
    af = build_app_frame(f, feats, State.NORMAL)
    assert af.status == "NORMAL"
    assert af.fall_prob == 0.0
    assert af.payload["video_clip_url"] is None
    assert af.payload["timestamp"] == 1735000000


def test_descending_state_emits_warning_prob():
    f, feats = _frame_and_feats()
    af = build_app_frame(f, feats, State.DESCENDING)
    assert af.status == "WARNING"
    assert 0.4 <= af.fall_prob < 0.7


def test_fallen_state_emits_fall_prob():
    f, feats = _frame_and_feats()
    af = build_app_frame(f, feats, State.FALLEN)
    assert af.status == "FALL"
    assert af.fall_prob >= 0.7


def test_confirmed_override_uses_higher_confidence():
    f, feats = _frame_and_feats()
    af = build_app_frame(f, feats, State.FALLEN, confirmed_confidence=0.95)
    assert af.status == "FALL"
    assert af.fall_prob == 0.95


def test_pose_data_has_33_landmarks_with_visibility():
    f, feats = _frame_and_feats()
    af = build_app_frame(f, feats, State.NORMAL)
    pd = af.payload["pose_data"]
    assert len(pd) == 33
    for lm in pd:
        assert set(lm.keys()) == {"x", "y", "z", "visibility"}
        assert 0.0 <= lm["visibility"] <= 1.0


def test_features_none_still_produces_payload():
    """가시성 미달 등으로 features=None인 frame도 stream 유지를 위해 페이로드 생성."""
    f = make_frame(99, 1735000099.0, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5, visibility=0.1)
    af = build_app_frame(f, None, State.NORMAL)
    assert af.payload["status"] == "NORMAL"
    assert len(af.payload["pose_data"]) == 33
