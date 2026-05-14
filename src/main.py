"""엔트리 포인트.

Phase 2: ZMQ 프레임 → FallDetector(rule gate) → MQTT 발행 (fall + status).

실행:
    python -m src.main
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from types import FrameType
from typing import Optional

from src.config import log_cfg, mqtt_cfg
from src.core.fall_detector import FallDetector, build_fall_payload
from src.io.mqtt_publisher import MqttPublisher
from src.io.zmq_subscriber import ZmqPoseSubscriber

log = logging.getLogger(__name__)


class App:
    def __init__(self) -> None:
        self.mqtt = MqttPublisher()
        self.zmq_sub = ZmqPoseSubscriber()
        self.detector = FallDetector()
        self._stop = False
        self._started_at = time.time()
        self._frames_received = 0
        self._falls_published = 0
        self._last_status_at = 0.0

    def _signal_handler(self, signum: int, _frame: Optional[FrameType]) -> None:
        log.info("signal %s received → shutting down", signum)
        self._stop = True

    def _maybe_publish_status(self) -> None:
        now = time.time()
        if now - self._last_status_at < mqtt_cfg.status_interval_sec:
            return
        uptime = now - self._started_at
        fps = self._frames_received / uptime if uptime > 0 else 0.0
        self.mqtt.publish_status(
            {
                "status": "normal",
                "stats": {
                    "uptime_sec": int(uptime),
                    "frames_received": self._frames_received,
                    "falls_published": self._falls_published,
                    "fps": round(fps, 2),
                },
            }
        )
        self._last_status_at = now

    def run(self) -> int:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.mqtt.connect()
        try:
            with self.zmq_sub as sub:
                for frame in sub.frames():
                    if self._stop:
                        break
                    if frame is not None:
                        self._frames_received += 1
                        event = self.detector.update(frame)
                        if event is not None:
                            payload = build_fall_payload(event)
                            self.mqtt.publish_fall(payload)
                            self._falls_published += 1
                            log.warning(
                                "FALL CONFIRMED conf=%.2f frame_id=%d",
                                event.confidence,
                                frame.frame_id,
                            )
                        if self._frames_received % 50 == 0:
                            hist = self.detector.gate.history
                            last = hist[-1] if hist else None
                            if last is not None:
                                log.info(
                                    "received %d frames, falls=%d, state=%s "
                                    "torso=%.1f° vert=%.2f aspect=%.2f hip_y=%.2f",
                                    self._frames_received,
                                    self._falls_published,
                                    self.detector.gate.state.name,
                                    last.torso_angle_deg,
                                    last.torso_vertical_extent,
                                    last.bbox_aspect,
                                    last.hip_center_y,
                                )
                            else:
                                log.info(
                                    "received %d frames, falls=%d (no valid features yet)",
                                    self._frames_received,
                                    self._falls_published,
                                )
                    self._maybe_publish_status()
        finally:
            self.mqtt.disconnect()
        return 0


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, log_cfg.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return App().run()


if __name__ == "__main__":
    sys.exit(main())
