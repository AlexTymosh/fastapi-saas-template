from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import get_request_id
from app.core.logging import LogCategory, get_logger

log = get_logger(__name__)


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code: int | None = None
        method = scope.get("method")
        path = scope.get("path")

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.exception(
                "request_failed",
                category=LogCategory.APPLICATION,
                method=method,
                path=path,
                status_code=500,
                duration_ms=duration_ms,
                request_id=get_request_id() or scope.get("request_id"),
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.info(
                "request_completed",
                category=LogCategory.APPLICATION,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=get_request_id() or scope.get("request_id"),
            )
