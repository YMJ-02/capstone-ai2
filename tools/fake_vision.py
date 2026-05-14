"""vision-pi 모킹: 무작위 또는 시나리오 기반 33 landmarks를 ZMQ로 발행.

시나리오:
    random  — 균등 난수 (Phase 1 연결 검증용)
    stable  — 직립 정지 자세 (오탐 검증용)
    fall    — 5초 직립 → 급강하 → 수평+정지 (낙상 검출 검증용)

실행:
    python tools/fake_vision.py --bind tcp://0.0.0.0:5555 --fps 10 --scenario fall
"""
from __future__ import annotations

import argparse
import json
import random
import time
from typing import List

import zmq


def _noisy(s: float) -> float:
    return random.uniform(-s, s)


def _stable_pose(hip_y: float = 0.5) -> List[dict]:
    """직립: 어깨가 엉덩이 위, 수직 정렬."""
    sh_y = hip_y - 0.25 + _noisy(0.005)
    sh_x_l, sh_x_r = 0.45 + _noisy(0.005), 0.55 + _noisy(0.005)
    hp_x_l, hp_x_r = 0.47 + _noisy(0.005), 0.53 + _noisy(0.005)
    lms = []
    for i in range(33):
        if i == 11:
            x, y = sh_x_l, sh_y
        elif i == 12:
            x, y = sh_x_r, sh_y
        elif i == 23:
            x, y = hp_x_l, hip_y
        elif i == 24:
            x, y = hp_x_r, hip_y
        elif i == 0:
            x, y = 0.5, sh_y - 0.15
        elif i in (25, 26):
            x = 0.48 if i == 25 else 0.52
            y = hip_y + 0.2
        elif i in (27, 28):
            x = 0.48 if i == 27 else 0.52
            y = hip_y + 0.4
        else:
            x, y = 0.5 + _noisy(0.02), sh_y + 0.1
        lms.append({
            "id": i, "x": round(x, 4), "y": round(y, 4),
            "z": round(_noisy(0.05), 4),
            "v": round(random.uniform(0.85, 1.0), 4),
        })
    return lms


def _lying_pose(hip_y: float = 0.82) -> List[dict]:
    """수평 누운 자세: 어깨-엉덩이 가로 정렬, hip_y 큼."""
    sh_x, sh_y = 0.3 + _noisy(0.005), hip_y + _noisy(0.01)
    hp_x, hp_y = 0.7 + _noisy(0.005), hip_y + _noisy(0.01)
    lms = []
    for i in range(33):
        if i == 11:
            x, y = sh_x, sh_y - 0.04
        elif i == 12:
            x, y = sh_x, sh_y + 0.04
        elif i == 23:
            x, y = hp_x, hp_y - 0.04
        elif i == 24:
            x, y = hp_x, hp_y + 0.04
        elif i == 0:
            x, y = sh_x - 0.12, sh_y
        elif i in (25, 26):
            x = hp_x + 0.12
            y = hp_y + 0.04 if i == 25 else hp_y - 0.04
        elif i in (27, 28):
            x = hp_x + 0.25
            y = hp_y + 0.04 if i == 27 else hp_y - 0.04
        else:
            x, y = (sh_x + hp_x) / 2 + _noisy(0.02), hip_y + _noisy(0.02)
        lms.append({
            "id": i, "x": round(x, 4), "y": round(y, 4),
            "z": round(_noisy(0.05), 4),
            "v": round(random.uniform(0.85, 1.0), 4),
        })
    return lms


def _random_pose() -> List[dict]:
    return [
        {
            "id": i,
            "x": round(random.uniform(0.2, 0.8), 4),
            "y": round(random.uniform(0.2, 0.8), 4),
            "z": round(random.uniform(-0.1, 0.1), 4),
            "v": round(random.uniform(0.8, 1.0), 4),
        }
        for i in range(33)
    ]


FALL_CYCLE_SEC = 30.0


def fall_scenario(t_elapsed: float) -> tuple[List[dict], str]:
    """30초 주기로 직립 → 급강하 → 누움 정지 → 일어남 → 직립을 반복.

    되돌아오는 두 번째 값은 현재 phase 이름 (로그용).
    """
    cycle = t_elapsed % FALL_CYCLE_SEC
    if cycle < 5.0:
        return _stable_pose(hip_y=0.5), "stable"
    if cycle < 5.4:
        progress = (cycle - 5.0) / 0.4
        hip_y = 0.5 + 0.35 * progress
        if progress > 0.6:
            return _lying_pose(hip_y=hip_y), "falling"
        return _stable_pose(hip_y=hip_y), "falling"
    if cycle < 15.0:
        return _lying_pose(hip_y=0.85), "lying"
    if cycle < 15.4:
        progress = (cycle - 15.0) / 0.4
        hip_y = 0.85 - 0.35 * progress
        if progress > 0.5:
            return _stable_pose(hip_y=hip_y), "standing_up"
        return _lying_pose(hip_y=hip_y), "standing_up"
    return _stable_pose(hip_y=0.5), "stable"


def make_payload(frame_id: int, landmarks: List[dict], node_id: str = "fake-vision-01") -> dict:
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
    p.add_argument("--scenario", choices=["random", "stable", "fall"], default="random")
    args = p.parse_args()

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUB)
    sock.bind(args.bind)
    period = 1.0 / max(args.fps, 0.1)
    print(
        f"[fake_vision] PUB bound on {args.bind} topic={args.topic} "
        f"fps={args.fps} scenario={args.scenario}"
    )
    if args.scenario == "fall":
        print(f"[fake_vision] fall cycle: stable(0-5s) → falling(5-5.4s) → "
              f"lying(5.4-15s) → standing_up(15-15.4s) → stable, "
              f"loops every {FALL_CYCLE_SEC:.0f}s")
    time.sleep(0.5)
    start = time.time()
    frame_id = 0
    last_phase = ""
    try:
        while True:
            t = time.time() - start
            phase = args.scenario
            if args.scenario == "random":
                lms = _random_pose()
            elif args.scenario == "stable":
                lms = _stable_pose()
            else:
                lms, phase = fall_scenario(t)
                if phase != last_phase:
                    print(f"[fake_vision] t={t:6.1f}s phase={phase}")
                    last_phase = phase
            sock.send_string(f"{args.topic} {json.dumps(make_payload(frame_id, lms))}")
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
