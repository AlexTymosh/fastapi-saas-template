from __future__ import annotations

import time

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.observability.metrics import (
    get_route_template,
    record_http_error,
    record_http_request,
    record_http_request_duration,
)


class HttpMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        method = scope.get("method", "UNKNOWN")
        route = get_route_template(Request(scope))
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            duration_seconds = time.perf_counter() - start
            record_http_request(
                method=method,
                route=route,
                status_code=500,
            )
            record_http_request_duration(
                method=method,
                route=route,
                status_code=500,
                duration_seconds=duration_seconds,
            )
            record_http_error(
                method=method,
                route=route,
                status_code=500,
                error_type=exc.__class__.__name__,
            )
            raise

        duration_seconds = time.perf_counter() - start
        record_http_request(
            method=method,
            route=route,
            status_code=status_code,
        )
        record_http_request_duration(
            method=method,
            route=route,
            status_code=status_code,
            duration_seconds=duration_seconds,
        )

        if status_code >= 500:
            record_http_error(
                method=method,
                route=route,
                status_code=status_code,
                error_type="http_5xx",
            )
