"""vision-pi (capstone-vision)로부터 자세 데이터를 수신한다.

메시지 형식 (docs/INPUT_SCHEMA.md 참조):
    "<topic> <json>"
    json = {node_id, frame_id, timestamp, image_size:[W,H],
            landmarks:[{id,x,y,z,v}, ... 33개]}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import zmq

from src.config import zmq_cfg

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoseFrame:
    node_id: str
    frame_id: int
    timestamp: float
    image_size: Tuple[int, int]
    landmarks: List[dict]

    @classmethod
    def from_payload(cls, payload: dict) -> "PoseFrame":
        landmarks = payload["landmarks"]
        if len(landmarks) != 33:
            raise ValueError(f"expected 33 landmarks, got {len(landmarks)}")
        size = payload["image_size"]
        return cls(
            node_id=str(payload["node_id"]),
            frame_id=int(payload["frame_id"]),
            timestamp=float(payload["timestamp"]),
            image_size=(int(size[0]), int(size[1])),
            landmarks=list(landmarks),
        )


class ZmqPoseSubscriber:
    """ZMQ SUB 래퍼. with 블록 또는 connect/close로 사용."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        topic: Optional[str] = None,
        recv_timeout_ms: Optional[int] = None,
    ) -> None:
        self.endpoint = endpoint or zmq_cfg.endpoint
        self.topic = topic or zmq_cfg.topic
        self.recv_timeout_ms = (
            recv_timeout_ms if recv_timeout_ms is not None else zmq_cfg.recv_timeout_ms
        )
        self._ctx = zmq.Context.instance()
        self._sock: Optional[zmq.Socket] = None

    def connect(self) -> None:
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.SUBSCRIBE, self.topic.encode())
        self._sock.setsockopt(zmq.RCVTIMEO, self.recv_timeout_ms)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.connect(self.endpoint)
        log.info("ZMQ SUB connected: endpoint=%s topic=%s", self.endpoint, self.topic)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
            log.info("ZMQ SUB closed")

    def __enter__(self) -> "ZmqPoseSubscriber":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def frames(self) -> Iterator[Optional[PoseFrame]]:
        """무한 제너레이터. 타임아웃 시 None을 yield하므로 호출자는 heartbeat 등 처리 가능."""
        if self._sock is None:
            raise RuntimeError("connect() first")
        while True:
            try:
                msg = self._sock.recv_string()
            except zmq.error.Again:
                yield None
                continue
            _topic, sep, raw = msg.partition(" ")
            if not sep:
                log.warning("malformed message (no space): %r", msg[:80])
                yield None
                continue
            try:
                payload = json.loads(raw)
                yield PoseFrame.from_payload(payload)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                log.warning("failed to parse pose frame: %s", e)
                yield None
