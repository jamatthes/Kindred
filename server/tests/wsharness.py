"""A minimal async WebSocket client that speaks ASGI directly to the app object.

Starlette's `TestClient` would be the obvious choice, but it is synchronous: it drives the
app from a worker thread with its own event loop, which would put the app's asyncpg pool on a
different loop from the async database fixtures. Talking to the ASGI callable ourselves keeps
everything on one loop, and makes the close code observable, which is exactly what F-8 needs
to assert.
"""

from __future__ import annotations

import asyncio
import json
from types import TracebackType
from typing import Any


class WebSocketDisconnected(Exception):
    """Raised when the server closed the socket. Carries the close ``code``."""

    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"closed with {code}")
        self.code = code
        self.reason = reason


class ASGIWebSocketClient:
    """Drive an ASGI app's WebSocket endpoint from the current event loop."""

    def __init__(self, app: Any, path: str, cookies: dict[str, str] | None = None) -> None:
        self.app = app
        self.path = path
        self.cookies = cookies or {}
        self.accepted = False
        self.close_code: int | None = None
        self._to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    # --- ASGI plumbing -------------------------------------------------------------------

    async def _receive(self) -> dict[str, Any]:
        return await self._to_app.get()

    async def _send(self, message: dict[str, Any]) -> None:
        await self._from_app.put(message)

    def _scope(self) -> dict[str, Any]:
        headers: list[tuple[bytes, bytes]] = [(b"host", b"test")]
        if self.cookies:
            cookie = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            headers.append((b"cookie", cookie.encode()))
        return {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 51234),
            "server": ("test", 80),
            "subprotocols": [],
            "state": {},
        }

    # --- lifecycle -----------------------------------------------------------------------

    async def connect(self) -> None:
        self._task = asyncio.create_task(self.app(self._scope(), self._receive, self._send))
        await self._to_app.put({"type": "websocket.connect"})
        message = await asyncio.wait_for(self._from_app.get(), timeout=5)
        if message["type"] == "websocket.accept":
            self.accepted = True
            return
        if message["type"] == "websocket.close":
            self.close_code = message.get("code", 1000)
            raise WebSocketDisconnected(self.close_code, message.get("reason", ""))
        raise AssertionError(f"unexpected first message: {message}")  # pragma: no cover

    async def receive_json(self, timeout: float = 5.0) -> dict[str, Any]:
        message = await asyncio.wait_for(self._from_app.get(), timeout=timeout)
        if message["type"] == "websocket.close":
            self.close_code = message.get("code", 1000)
            raise WebSocketDisconnected(self.close_code, message.get("reason", ""))
        if "text" in message and message["text"] is not None:
            return json.loads(message["text"])
        return json.loads(message["bytes"].decode())  # pragma: no cover

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def disconnect(self, code: int = 1000) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": code})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):  # pragma: no cover
                self._task.cancel()

    async def __aenter__(self) -> ASGIWebSocketClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.disconnect()
