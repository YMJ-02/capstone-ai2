"""vision-pi 모킹: 무작위 33 landmarks를 ZMQ로 발행. Phase 1 연결 검증용.

실행 (vision-pi 대신 같은 머신에서 띄우면 됨):
    python tools/fake_vision.py --bind tcp://0.0.0.0:5555 --fps 10
"""
from __future__ import annotations

import argparse
import json
import random
import time

import zmq


def make_payload(frame_id: int, node_id: str = "fake-vision-01") -> dict:
    landmarks = [
        {
            "id": i,
            "x": round(random.uniform(0.2, 0.8), 4),
            "y": round(random.uniform(0.2, 0.8), 4),
            "z": round(random.uniform(-0.1, 0.1), 4),
            "v": round(random.uniform(0.8, 1.0), 4),
        }
        for i in range(33)
    ]
    return {
        "node_id": node_id,
        "frame_id": frame_id,
        "timestamp": time.time(),
        "image_size": [640, 480],
        "landmarks": landmarks,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default="tcp://0.0.0.0:5555")
    p.add_argument("--topic", default="pose")
    p.add_argument("--fps", type=float, default=10.0)
    args = p.parse_args()

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUB)
    sock.bind(args.bind)
    period = 1.0 / max(args.fps, 0.1)
    print(f"[fake_vision] PUB bound on {args.bind} topic={args.topic} fps={args.fps}")
    time.sleep(0.5)
    frame_id = 0
    try:
        while True:
            payload = make_payload(frame_id)
            sock.send_string(f"{args.topic} {json.dumps(payload)}")
            frame_id += 1
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        ctx.term()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
