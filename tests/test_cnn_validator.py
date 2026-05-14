"""CNN validator 기본 동작 검증.

모델 파일이 없는 환경에서도 깨지지 않고 None을 반환해야 한다 (fail-safe).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.cnn_validator import CnnValidator, WINDOW_LEN
from tests.conftest import make_frame
from src.pipeline.features import extract


def _models_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "models"


def _runtime_available(model_path: Path) -> bool:
    """TFLite 추론 라이브러리(tflite_runtime 또는 tensorflow)가 실제로 로드되는지 확인.

    Pi에 둘 다 없는 환경에서는 CnnValidator가 자동 비활성화되는데, 이때 추론 검증
    테스트는 환경 문제이지 코드 결함이 아니므로 skip이 적절.
    """
    v = CnnValidator(model_path=str(model_path))
    if not v.enabled:
        return False
    return v._ensure_interp()


def test_validator_disabled_when_no_model(tmp_path):
    """모델 없으면 enabled=False, predict None."""
    v = CnnValidator(model_path=str(tmp_path / "nonexistent.tflite"))
    assert v.enabled is False
    # observe 호출은 안전해야 함
    f = extract(make_frame(0, 0.0, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5))
    v.observe(f)
    assert v.predict() is None


def test_validator_returns_none_before_window_full():
    model = _models_dir() / "fall_validator.tflite"
    if not model.exists():
        pytest.skip("모델 미학습 (python -m ml.train 으로 생성)")
    if not _runtime_available(model):
        pytest.skip("TFLite 런타임 미설치")
    v = CnnValidator(model_path=str(model))
    for i in range(5):
        f = extract(make_frame(i, i * 0.1, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5))
        v.observe(f)
    assert v.predict() is None  # WINDOW_LEN(30) 미만


def test_validator_distinguishes_stable_vs_fall():
    """학습된 모델이라면 stable과 fall을 명확히 구분해야 한다."""
    model = _models_dir() / "fall_validator.tflite"
    if not model.exists():
        pytest.skip("모델 미학습 (python -m ml.train 으로 생성)")
    if not _runtime_available(model):
        pytest.skip("TFLite 런타임 미설치 (pip install tflite-runtime 또는 tensorflow)")

    v_stable = CnnValidator(model_path=str(model))
    for i in range(WINDOW_LEN + 5):
        f = extract(make_frame(i, i * 0.1, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5))
        v_stable.observe(f)
    p_stable = v_stable.predict()

    v_fall = CnnValidator(model_path=str(model))
    # 직립 → 누움 (1초 직립, 0.3초 강하, 2초 누움)
    for i in range(10):
        f = extract(make_frame(i, i * 0.1, sh_x=0.5, sh_y=0.3, hp_x=0.5, hp_y=0.5))
        v_fall.observe(f)
    for k, hy in enumerate([0.6, 0.75, 0.85]):
        f = extract(make_frame(10 + k, 1.0 + (k + 1) * 0.1,
                               sh_x=0.5, sh_y=0.3 + 0.05 * k, hp_x=0.5, hp_y=hy))
        v_fall.observe(f)
    for k in range(20):
        f = extract(make_frame(13 + k, 1.3 + k * 0.1,
                               sh_x=0.3, sh_y=0.85, hp_x=0.7, hp_y=0.85))
        v_fall.observe(f)
    p_fall = v_fall.predict()

    assert p_stable is not None and p_fall is not None
    assert p_stable < 0.3, f"stable should be low, got {p_stable}"
    assert p_fall > 0.7, f"fall should be high, got {p_fall}"
