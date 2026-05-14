"""capstone-app(Flutter) 어댑터용 WebSocket 브로드캐스터.

별도 thread에서 asyncio 이벤트 루프를 돌리고, sync 코드(main.py)는 broadcast()로
페이로드를 큐에 던진다. 모든 연결된 client에 broadcast.

특성:
- 연결 client 0개여도 안전 (큐 소비만 일어남)
- 연결 끊긴 client는 자동 정리
- main 루프 블로킹 없음 (큐는 nowait, 가득 차면 가장 오래된 frame drop)
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from src.config import app_cfg

log = logging.getLogger(__name__)


class WebsocketBroadcaster:
    """매 frame 페이로드를 broadcast하는 비동기 서버 래퍼.

    Usage:
        ws = WebsocketBroadcaster()
        ws.start()
        ...
        ws.broadcast({"timestamp": ..., "fall_prob": ..., ...})
        ws.stop()
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        max_queue: int = 32,
    ) -> None:
        self.host = host or app_cfg.ws_host
        self.port = port or app_cfg.ws_port
        self._max_queue = max_queue
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None
        self._clients: Set[WebSocketServerProtocol] = set()
        self._stop_event: Optional[asyncio.Event] = None
        self._ready = threading.Event()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="ws-broadcaster", daemon=True)
        self._thread.start()
        # asyncio 루프가 시작될 때까지 대기 (broadcast 호출 전에 보장)
        if not self._ready.wait(timeout=3.0):
            log.warning("WS broadcaster start timeout — 큐 호출이 실패할 수 있음")

    def stop(self) -> None:
        if self._loop is None or not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._signal_stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def broadcast(self, payload: Any) -> None:
        """sync 코드에서 호출. 큐에 nowait로 던진다. 가득 차면 가장 오래된 frame을 drop."""
        if self._loop is None or self._queue is None:
            return
        try:
            msg = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            log.warning("WS payload serialize 실패: %s", e)
            return
        self._loop.call_soon_threadsafe(self._enqueue, msg)

    def _enqueue(self, msg: str) -> None:
        assert self._queue is not None
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    def _signal_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue(maxsize=self._max_queue)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:  # noqa: BLE001
            log.error("WS broadcaster crashed: %s", e)
        finally:
            self._loop.close()

    async def _main(self) -> None:
        assert self._stop_event is not None
        async with serve(self._handler, self.host, self.port):
            log.info("WS broadcaster listening on ws://%s:%d", self.host, self.port)
            self._ready.set()
            consumer = asyncio.create_task(self._consume())
            await self._stop_event.wait()
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass
        log.info("WS broadcaster stopped")

    async def _handler(self, ws: WebSocketServerProtocol) -> None:
        peer = getattr(ws, "remote_address", None)
        self._clients.add(ws)
        log.info("WS client connected from %s (총 %d)", peer, len(self._clients))
        try:
            # 앱은 단방향 수신만 하지만 close 감지 위해 idle 유지
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)
            log.info("WS client disconnected from %s (남은 %d)", peer, len(self._clients))

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            if not self._clients:
                continue
            await asyncio.gather(
                *[self._safe_send(c, msg) for c in list(self._clients)],
                return_exceptions=True,
            )

    @staticmethod
    async def _safe_send(client: WebSocketServerProtocol, msg: str) -> None:
        try:
            await client.send(msg)
        except ConnectionClosed:
            pass
        except Exception as e:  # noqa: BLE001
            log.debug("WS send 실패: %s", e)
