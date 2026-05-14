"""중앙 설정. 모든 임계값/엔드포인트를 한곳에 모으고 .env로 오버라이드한다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_PATH)


def _env(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(_env(key, str(default)))


def _env_opt(key: str) -> Optional[str]:
    v = os.getenv(key)
    return v if v not in (None, "") else None


@dataclass(frozen=True)
class ZmqConfig:
    endpoint: str = _env("ZMQ_ENDPOINT", "tcp://127.0.0.1:5555")
    topic: str = _env("ZMQ_TOPIC", "pose")
    recv_timeout_ms: int = _env_int("ZMQ_RECV_TIMEOUT_MS", 1000)


@dataclass(frozen=True)
class MqttConfig:
    host: str = _env("MQTT_HOST", "127.0.0.1")
    port: int = _env_int("MQTT_PORT", 1883)
    username: Optional[str] = _env_opt("MQTT_USERNAME")
    password: Optional[str] = _env_opt("MQTT_PASSWORD")
    client_id: str = _env("MQTT_CLIENT_ID", "edgesafe-ai-pi02")
    topic_fall: str = _env("MQTT_TOPIC_FALL", "edgesafe/ai/fall")
    topic_status: str = _env("MQTT_TOPIC_STATUS", "edgesafe/ai/status")
    keepalive_sec: int = _env_int("MQTT_KEEPALIVE_SEC", 30)
    status_interval_sec: int = _env_int("STATUS_INTERVAL_SEC", 10)


@dataclass(frozen=True)
class NodeConfig:
    node_id: str = _env("NODE_ID", "ai-pi-02")
    camera_label: str = _env("CAMERA_LABEL", "vision-pi-01")
    location_label: str = _env("LOCATION_LABEL", "거실")
    schema_version: str = _env("SCHEMA_VERSION", "1.1")
    fps_target: int = _env_int("FPS_TARGET", 10)


@dataclass(frozen=True)
class RuleConfig:
    """Phase 2에서 사용. 임계값은 기존 edgesafe-ai-pi2 기준으로 초기값 부여."""
    window_size: int = _env_int("WINDOW_SIZE", 20)
    hip_drop_velocity_thresh: float = _env_float("HIP_DROP_VELOCITY_THRESH", 0.6)
    torso_angle_horizontal_deg: float = _env_float("TORSO_ANGLE_HORIZONTAL_DEG", 55.0)
    bbox_aspect_ratio_thresh: float = _env_float("BBOX_ASPECT_RATIO_THRESH", 1.1)
    # shoulder-hip 수직거리. 누우면 작아진다 (정규화 좌표 0~1 기준).
    # 직립 약 0.25, 누움 약 0.05 → 0.12 정도면 누움으로 판정.
    torso_vertical_extent_thresh: float = _env_float(
        "TORSO_VERTICAL_EXTENT_THRESH", 0.12
    )
    descending_to_fallen_timeout_sec: float = _env_float(
        "DESCENDING_TO_FALLEN_TIMEOUT_SEC", 2.5
    )
    # FALLEN 진입 후 이 시간 이상 누워있으면 stillness 무관하게 확정.
    # 실 환경에서 의식 있는 사람이 움직이는 경우 stillness가 못 잡는 케이스 대응.
    fallen_confirm_timeout_sec: float = _env_float("FALLEN_CONFIRM_TIMEOUT_SEC", 1.5)
    # FALLEN에서 non-horizontal이 이 시간 이상 지속되어야 NORMAL로 탈출.
    # 한 프레임 노이즈(손 들기 등)로 즉시 탈출하는 것을 방지.
    fallen_exit_sustain_sec: float = _env_float("FALLEN_EXIT_SUSTAIN_SEC", 0.5)
    stillness_window_sec: float = _env_float("STILLNESS_WINDOW_SEC", 0.8)
    stillness_motion_thresh: float = _env_float("STILLNESS_MOTION_THRESH", 0.10)
    landmark_visibility_thresh: float = _env_float("LANDMARK_VISIBILITY_THRESH", 0.5)
    fall_cooldown_sec: float = _env_float("FALL_COOLDOWN_SEC", 5.0)


@dataclass(frozen=True)
class LogConfig:
    level: str = _env("LOG_LEVEL", "INFO")


zmq_cfg = ZmqConfig()
mqtt_cfg = MqttConfig()
node_cfg = NodeConfig()
rule_cfg = RuleConfig()
log_cfg = LogConfig()
