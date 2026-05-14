"""엔트리 포인트. Phase 1: ZMQ에서 프레임을 받고 MQTT status heartbeat를 발행한다.

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
from src.io.mqtt_publisher import MqttPublisher
from src.io.zmq_subscriber import ZmqPoseSubscriber

log = logging.getLogger(__name__)


class App:
    def __init__(self) -> None:
        self.mqtt = MqttPublisher()
        self.zmq_sub = ZmqPoseSubscriber()
        self._stop = False
        self._started_at = time.time()
        self._frames_received = 0
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
                        if self._frames_received % 50 == 0:
                            log.info(
                                "received %d frames, latest frame_id=%d",
                                self._frames_received,
                                frame.frame_id,
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
