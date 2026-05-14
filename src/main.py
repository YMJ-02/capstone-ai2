"""엔트리 포인트.

ZMQ 프레임 → FallDetector(rule + cnn) → MQTT 발행 (fall + status)
                                     → WebSocket broadcast (capstone-app 어댑터, 매 frame)
                                     → HTTP /health (capstone-app 헬스 체크)

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

from src.config import app_cfg, log_cfg, mqtt_cfg
from src.core.fall_detector import FallDetector, build_fall_payload
from src.io.http_health import HealthServer
from src.io.mqtt_publisher import MqttPublisher
from src.io.websocket_server import WebsocketBroadcaster
from src.io.zmq_subscriber import ZmqPoseSubscriber
from src.pipeline.app_payload import build_app_frame

log = logging.getLogger(__name__)


class App:
    def __init__(self) -> None:
        self.mqtt = MqttPublisher()
        self.zmq_sub = ZmqPoseSubscriber()
        self.detector = FallDetector()
        self.ws: Optional[WebsocketBroadcaster] = None
        self.http: Optional[HealthServer] = None
        if app_cfg.enabled:
            self.ws = WebsocketBroadcaster()
            self.http = HealthServer(ws_client_count_provider=lambda: self.ws.client_count if self.ws else 0)
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
        ws_clients = self.ws.client_count if self.ws else 0
        self.mqtt.publish_status(
            {
                "status": "normal",
                "stats": {
                    "uptime_sec": int(uptime),
                    "frames_received": self._frames_received,
                    "falls_published": self._falls_published,
                    "fps": round(fps, 2),
                    "ws_clients": ws_clients,
                },
            }
        )
        self._last_status_at = now

    def run(self) -> int:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.mqtt.connect()
        if self.ws is not None:
            self.ws.start()
        if self.http is not None:
            self.http.start()
        try:
            with self.zmq_sub as sub:
                for frame in sub.frames():
                    if self._stop:
                        break
                    if frame is not None:
                        self._frames_received += 1
                        update = self.detector.update(frame)

                        confirmed_conf: Optional[float] = None
                        if update.event is not None:
                            payload = build_fall_payload(update.event)
                            self.mqtt.publish_fall(payload)
                            self._falls_published += 1
                            confirmed_conf = update.event.confidence
                            log.warning(
                                "FALL CONFIRMED conf=%.2f frame_id=%d",
                                update.event.confidence,
                                frame.frame_id,
                            )

                        # capstone-app 어댑터로 매 frame 송신 (가시성 미달 frame도 stream 유지).
                        if self.ws is not None:
                            af = build_app_frame(frame, update.features, update.state, confirmed_conf)
                            self.ws.broadcast(af.payload)

                        if self._frames_received % 50 == 0:
                            hist = self.detector.gate.history
                            last = hist[-1] if hist else None
                            ws_clients = self.ws.client_count if self.ws else 0
                            if last is not None:
                                log.info(
                                    "received %d frames, falls=%d, state=%s "
                                    "torso=%.1f° vert=%.2f aspect=%.2f hip_y=%.2f ws_clients=%d",
                                    self._frames_received,
                                    self._falls_published,
                                    self.detector.gate.state.name,
                                    last.torso_angle_deg,
                                    last.torso_vertical_extent,
                                    last.bbox_aspect,
                                    last.hip_center_y,
                                    ws_clients,
                                )
                            else:
                                log.info(
                                    "received %d frames, falls=%d, ws_clients=%d (no valid features yet)",
                                    self._frames_received,
                                    self._falls_published,
                                    ws_clients,
                                )
                    self._maybe_publish_status()
        finally:
            if self.http is not None:
                self.http.stop()
            if self.ws is not None:
                self.ws.stop()
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
