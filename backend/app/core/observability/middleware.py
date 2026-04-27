from __future__ import annotations

import time
from collections.abc import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.observability.metrics import (
    get_route_template,
    record_http_error,
    record_http_request,
    record_http_request_duration,
)

log = get_logger(__name__)


class HttpMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _run_metrics_recorder_safely(
        recorder: Callable[..., None], *, metric_name: str, event: str, **kwargs: object
    ) -> None:
        try:
            recorder(**kwargs)
        except Exception as exc:
            log.warning(
                "metrics_recording_failed",
                metric_name=metric_name,
                event=event,
                reason=exc.__class__.__name__,
                category="observability",
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        method = scope.get("method", "UNKNOWN")
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            route = get_route_template(Request(scope))
            duration_seconds = time.perf_counter() - start
            self._run_metrics_recorder_safely(
                record_http_request,
                metric_name="http.server.requests.total",
                event="http_request",
                method=method,
                route=route,
                status_code=500,
            )
            self._run_metrics_recorder_safely(
                record_http_request_duration,
                metric_name="http.server.request.duration",
                event="http_request_duration",
                method=method,
                route=route,
                status_code=500,
                duration_seconds=duration_seconds,
            )
            self._run_metrics_recorder_safely(
                record_http_error,
                metric_name="http.server.errors.total",
                event="http_error",
                method=method,
                route=route,
                status_code=500,
                error_type=exc.__class__.__name__,
            )
            raise

        route = get_route_template(Request(scope))
        duration_seconds = time.perf_counter() - start
        self._run_metrics_recorder_safely(
            record_http_request,
            metric_name="http.server.requests.total",
            event="http_request",
            method=method,
            route=route,
            status_code=status_code,
        )
        self._run_metrics_recorder_safely(
            record_http_request_duration,
            metric_name="http.server.request.duration",
            event="http_request_duration",
            method=method,
            route=route,
            status_code=status_code,
            duration_seconds=duration_seconds,
        )

        if status_code >= 500:
            self._run_metrics_recorder_safely(
                record_http_error,
                metric_name="http.server.errors.total",
                event="http_error",
                method=method,
                route=route,
                status_code=status_code,
                error_type="http_5xx",
            )
