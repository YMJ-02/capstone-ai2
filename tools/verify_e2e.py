"""Phase 5 E2E 검증 보조 스크립트.

각 서브시스템(import / MQTT / ZMQ)을 격리 검증한다. 라즈베리파이에서:

    python tools/verify_e2e.py --check imports
    python tools/verify_e2e.py --check mqtt
    python tools/verify_e2e.py --check zmq --timeout 5
    python tools/verify_e2e.py --check all
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK = "[ OK ]"
FAIL = "[FAIL]"


def _ok(msg: str) -> None:
    print(f"{OK} {msg}")


def _fail(msg: str) -> None:
    print(f"{FAIL} {msg}")


def check_imports() -> bool:
    failed = []
    for mod in [
        "src.config",
        "src.io.zmq_subscriber",
        "src.io.mqtt_publisher",
        "src.core.event_builder",
        "src.core.fall_detector",
        "src.pipeline.features",
        "src.pipeline.rule_gate",
        "src.pipeline.cnn_validator",
    ]:
        try:
            __import__(mod)
            _ok(f"import {mod}")
        except Exception as e:  # noqa: BLE001
            _fail(f"import {mod}: {e}")
            failed.append(mod)
    return not failed


def check_mqtt() -> bool:
    import paho.mqtt.client as mqtt  # type: ignore

    from src.config import mqtt_cfg

    received = threading.Event()
    payload_in: Optional[str] = None

    def on_message(_c, _u, msg):
        nonlocal payload_in
        payload_in = msg.payload.decode("utf-8", errors="replace")
        received.set()

    c = mqtt.Client(client_id="verify-e2e", clean_session=True)
    if mqtt_cfg.username:
        c.username_pw_set(mqtt_cfg.username, mqtt_cfg.password or "")
    c.on_message = on_message
    try:
        c.connect(mqtt_cfg.host, mqtt_cfg.port, keepalive=10)
    except Exception as e:  # noqa: BLE001
        _fail(f"MQTT connect {mqtt_cfg.host}:{mqtt_cfg.port} — {e}")
        return False
    _ok(f"MQTT connect {mqtt_cfg.host}:{mqtt_cfg.port}")

    test_topic = "edgesafe/ai/verify"
    c.loop_start()
    c.subscribe(test_topic, qos=1)
    time.sleep(0.3)
    test_body = json.dumps({"ping": int(time.time())})
    c.publish(test_topic, test_body, qos=1)
    ok = received.wait(timeout=3.0)
    c.loop_stop()
    c.disconnect()
    if ok and payload_in == test_body:
        _ok("subscribe self-publish round-trip")
        return True
    _fail(f"round-trip failed (got={payload_in!r})")
    return False


def check_zmq(timeout: float) -> bool:
    from src.config import zmq_cfg
    from src.io.zmq_subscriber import ZmqPoseSubscriber

    deadline = time.time() + timeout
    with ZmqPoseSubscriber() as sub:
        _ok(f"ZMQ subscribe {zmq_cfg.endpoint} topic={zmq_cfg.topic}")
        got = 0
        for frame in sub.frames():
            if frame is not None:
                got += 1
                _ok(
                    f"got 1 pose frame node_id={frame.node_id} "
                    f"frame_id={frame.frame_id} landmarks={len(frame.landmarks)}"
                )
                return True
            if time.time() > deadline:
                _fail(f"no frame in {timeout:.1f}s (got={got})")
                return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--check",
        choices=["imports", "mqtt", "zmq", "all"],
        default="all",
    )
    p.add_argument("--timeout", type=float, default=5.0, help="zmq check timeout sec")
    args = p.parse_args()

    results = {}
    if args.check in ("imports", "all"):
        results["imports"] = check_imports()
    if args.check in ("mqtt", "all"):
        results["mqtt"] = check_mqtt()
    if args.check in ("zmq", "all"):
        results["zmq"] = check_zmq(args.timeout)

    print()
    print("=" * 40)
    all_ok = all(results.values())
    for k, v in results.items():
        print(f"  {k:8s}: {'OK' if v else 'FAIL'}")
    print("=" * 40)
    if all_ok:
        print("ALL CHECKS PASSED")
        return 0
    print("SOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
