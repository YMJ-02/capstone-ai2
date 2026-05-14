"""capstone-app(Flutter) 어댑터용 HTTP 헬스 서버.

stdlib http.server.ThreadingHTTPServer로 가벼운 /health 엔드포인트만 제공.
영상(/recordings, /stream)은 본 노드 범위 밖이라 미구현. 호출 시 404 반환.

앱은 AppConfig.videoServerBase (:8080) 가 살아있는지 확인하는 용도로만 사용.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from src.config import app_cfg

log = logging.getLogger(__name__)


class HealthServer:
    """별도 thread에서 동작하는 stdlib HTTP 서버.

    Usage:
        srv = HealthServer(ws_client_count_provider=lambda: ws.client_count)
        srv.start()
        ...
        srv.stop()
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        ws_client_count_provider: Optional[Callable[[], int]] = None,
    ) -> None:
        self.host = host or app_cfg.http_host
        self.port = port or app_cfg.http_port
        self._ws_count = ws_client_count_provider or (lambda: 0)
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return
        handler_cls = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="http-health",
            daemon=True,
        )
        self._thread.start()
        log.info("HTTP health server listening on http://%s:%d/health", self.host, self.port)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        log.info("HTTP health server stopped")

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        ws_count = self._ws_count

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:  # noqa: A003
                log.debug("[http] " + fmt, *args)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") in ("/health", ""):
                    body = json.dumps({"status": "ok", "ws_clients": ws_count()}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404, "endpoint not implemented")

        return _Handler
