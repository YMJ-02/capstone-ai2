"""WebSocket broadcaster + HTTP health server 통합 sanity.

별도 thread로 서버를 띄우고 실제 client로 round-trip 검증.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
import urllib.request
from contextlib import closing

import pytest

from src.io.http_health import HealthServer
from src.io.websocket_server import WebsocketBroadcaster


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_health_server_returns_ok_json():
    port = _free_port()
    srv = HealthServer(host="127.0.0.1", port=port, ws_client_count_provider=lambda: 3)
    srv.start()
    try:
        time.sleep(0.1)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            assert r.status == 200
            body = json.loads(r.read())
            assert body["status"] == "ok"
            assert body["ws_clients"] == 3
    finally:
        srv.stop()


def test_health_server_404_on_unknown_path():
    port = _free_port()
    srv = HealthServer(host="127.0.0.1", port=port)
    srv.start()
    try:
        time.sleep(0.1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/recordings/x.mp4", timeout=2)
            assert False, "should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_websocket_broadcaster_round_trip():
    """클라이언트가 붙은 상태에서 broadcast → client가 페이로드 수신."""
    pytest.importorskip("websockets")
    import websockets as ws_client_mod

    port = _free_port()
    br = WebsocketBroadcaster(host="127.0.0.1", port=port)
    br.start()
    try:
        time.sleep(0.2)  # 서버 listen 대기

        async def client_recv() -> dict:
            async with ws_client_mod.connect(f"ws://127.0.0.1:{port}") as ws:
                # 서버가 broadcast하도록 약간 대기 후 trigger
                await asyncio.sleep(0.1)
                br.broadcast({"timestamp": 1, "fall_prob": 0.9, "status": "FALL"})
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(msg)

        body = asyncio.run(client_recv())
        assert body["status"] == "FALL"
        assert body["fall_prob"] == 0.9
    finally:
        br.stop()


def test_websocket_broadcaster_with_no_client_does_not_block():
    """client 0개여도 broadcast가 main loop를 블로킹하지 않아야 함."""
    port = _free_port()
    br = WebsocketBroadcaster(host="127.0.0.1", port=port)
    br.start()
    try:
        time.sleep(0.2)
        start = time.time()
        for i in range(100):
            br.broadcast({"timestamp": i, "fall_prob": 0.0, "status": "NORMAL"})
        elapsed = time.time() - start
        # 100회 broadcast가 1초 안에 끝나야 함 (실제로는 ms 이내)
        assert elapsed < 1.0, f"broadcast가 blocking됐을 가능성 (elapsed={elapsed:.2f}s)"
    finally:
        br.stop()
