"""1D-CNN 2차 검증기. TFLite 추론으로 fall_probability를 반환.

설계 원칙:
- **선택적**: 모델 파일이 없으면 자동 비활성화 (None 반환). 시스템은 규칙 게이트만으로
  동작 가능. 학습이 안 되어 있어도 빌드/실행이 깨지지 않는다.
- **지연 로드**: __init__에서 파일만 확인, 첫 호출 때 interpreter 생성.
- **런타임 의존성 최소화**: tflite_runtime이 있으면 우선 사용, 없으면 full TF로 폴백.

학습 코드는 ml/ 하위. 런타임은 본 모듈만 사용.
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

import numpy as np

from src.config import cnn_cfg
from src.pipeline.features import Features

log = logging.getLogger(__name__)

# 학습-추론 mismatch 방지: 채널/정규화 정의를 한 곳에.
WINDOW_LEN = 30
N_FEATURES = 5


def _normalize_row(f: Features, hip_velocity: float) -> List[float]:
    """ml.feature_window.normalize_row와 동일 공식 유지."""
    return [
        max(0.0, min(1.0, f.torso_angle_deg / 180.0)),
        max(0.0, min(1.0, f.torso_vertical_extent / 0.5)),
        max(0.0, min(1.0, f.bbox_aspect / 3.0)),
        max(0.0, min(1.5, f.hip_center_y)) / 1.5,
        1.0 / (1.0 + np.exp(-hip_velocity)),
    ]


class CnnValidator:
    def __init__(self, model_path: Optional[str] = None) -> None:
        self._path = Path(model_path or cnn_cfg.model_path)
        self._interp = None
        self._in_idx: Optional[int] = None
        self._out_idx: Optional[int] = None
        self._rows: Deque[List[float]] = deque(maxlen=WINDOW_LEN)
        self._prev_hip_y: Optional[float] = None

        if not self._path.exists():
            log.warning(
                "CNN validator 비활성화: 모델 파일 없음 (%s). rule_gate 단독으로 동작.",
                self._path,
            )
            self.enabled = False
        else:
            self.enabled = True
            log.info("CNN validator 활성화 (model=%s)", self._path)

    def _ensure_interp(self) -> bool:
        if self._interp is not None:
            return True
        if not self.enabled:
            return False
        try:
            # 세 가지 런타임을 차례로 시도: tflite-runtime(가장 가벼움) →
            # ai-edge-litert(최신 LiteRT) → tensorflow(가장 무겁지만 만능).
            Interpreter = None
            for mod_path in (
                "tflite_runtime.interpreter",
                "ai_edge_litert.interpreter",
            ):
                try:
                    Interpreter = getattr(__import__(mod_path, fromlist=["Interpreter"]),
                                          "Interpreter")
                    break
                except ImportError:
                    continue
            if Interpreter is None:
                import tensorflow as _tf  # type: ignore
                Interpreter = _tf.lite.Interpreter  # type: ignore
            self._interp = Interpreter(model_path=str(self._path))
            self._interp.allocate_tensors()
            self._in_idx = self._interp.get_input_details()[0]["index"]
            self._out_idx = self._interp.get_output_details()[0]["index"]
            log.info("TFLite interpreter 로드 완료")
            return True
        except Exception as e:  # noqa: BLE001
            log.error("TFLite 로드 실패 — CNN 비활성화: %s", e)
            self.enabled = False
            return False

    def observe(self, f: Features) -> None:
        """매 프레임 호출. window를 갱신만 하고 추론은 하지 않는다."""
        if not self.enabled:
            return
        if self._prev_hip_y is None:
            vel = 0.0
        else:
            vel = (f.hip_center_y - self._prev_hip_y) * 10.0  # 대략 10fps 기준
        self._prev_hip_y = f.hip_center_y
        self._rows.append(_normalize_row(f, vel))

    def predict(self) -> Optional[float]:
        """현재 window에 대한 fall 확률. window 부족하거나 비활성화 시 None."""
        if not self._ensure_interp():
            return None
        if len(self._rows) < WINDOW_LEN:
            return None
        x = np.asarray(self._rows, dtype=np.float32).reshape(1, WINDOW_LEN, N_FEATURES)
        self._interp.set_tensor(self._in_idx, x)
        self._interp.invoke()
        y = self._interp.get_tensor(self._out_idx)
        return float(y.flatten()[0])
