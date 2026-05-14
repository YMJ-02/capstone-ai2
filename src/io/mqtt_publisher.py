"""MQTT 발행. status heartbeat, fall 이벤트, LWT 지원.

OUTPUT_SCHEMA v1.1 기준. envelope는 event_builder가 만든다.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict

import paho.mqtt.client as mqtt

from src.config import mqtt_cfg
from src.core.event_builder import build_envelope

log = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self) -> None:
        self._client = mqtt.Client(client_id=mqtt_cfg.client_id, clean_session=False)
        if mqtt_cfg.username:
            self._client.username_pw_set(mqtt_cfg.username, mqtt_cfg.password or "")

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        lwt_body = json.dumps(
            build_envelope("status", {"status": "offline", "reason": "lwt"}),
            ensure_ascii=False,
        )
        self._client.will_set(mqtt_cfg.topic_status, lwt_body, qos=1, retain=True)

        self._connected = threading.Event()

    def connect(self, wait_timeout_sec: float = 5.0) -> None:
        log.info("MQTT connecting to %s:%d", mqtt_cfg.host, mqtt_cfg.port)
        self._client.connect(mqtt_cfg.host, mqtt_cfg.port, keepalive=mqtt_cfg.keepalive_sec)
        self._client.loop_start()
        if not self._connected.wait(timeout=wait_timeout_sec):
            log.warning("MQTT connect timeout — background loop will retry")

    def disconnect(self) -> None:
        try:
            self.publish_status({"status": "offline", "reason": "shutdown"}, retain=True)
            time.sleep(0.2)
        finally:
            self._client.loop_stop()
            self._client.disconnect()
            log.info("MQTT disconnected")

    def _on_connect(self, _c, _u, _f, rc) -> None:
        if rc == 0:
            log.info("MQTT connected")
            self._connected.set()
            self.publish_status({"status": "online"}, retain=True)
        else:
            log.error("MQTT connect failed rc=%s", rc)

    def _on_disconnect(self, _c, _u, rc) -> None:
        self._connected.clear()
        log.warning("MQTT disconnected rc=%s", rc)

    def publish_status(self, payload: Dict[str, Any], retain: bool = True) -> None:
        body = json.dumps(build_envelope("status", payload), ensure_ascii=False)
        self._client.publish(mqtt_cfg.topic_status, body, qos=1, retain=retain)
        log.debug("status published: %s", payload.get("status"))

    def publish_fall(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(build_envelope("fall_detected", payload), ensure_ascii=False)
        self._client.publish(mqtt_cfg.topic_fall, body, qos=1, retain=False)
        log.info("fall published: event_id=%s", payload.get("event_id"))
