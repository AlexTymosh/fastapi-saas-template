from __future__ import annotations

import time

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


def _safe_emit_metrics(
    *,
    metric_name: str,
    metric_event: str,
    operation,
    **kwargs: object,
) -> None:
    try:
        operation(**kwargs)
    except Exception as exc:
        try:
            log.warning(
                "metrics_recording_failed",
                metric_name=metric_name,
                metric_event=metric_event,
                reason=exc.__class__.__name__,
                category="observability",
            )
        except Exception:
            return


class HttpMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

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
            _safe_emit_metrics(
                metric_name="http.server.requests.total",
                metric_event="http_request",
                operation=record_http_request,
                method=method,
                route=route,
                status_code=500,
            )
            _safe_emit_metrics(
                metric_name="http.server.request.duration",
                metric_event="http_request_duration",
                operation=record_http_request_duration,
                method=method,
                route=route,
                status_code=500,
                duration_seconds=duration_seconds,
            )
            _safe_emit_metrics(
                metric_name="http.server.errors.total",
                metric_event="http_error",
                operation=record_http_error,
                method=method,
                route=route,
                status_code=500,
                error_type=exc.__class__.__name__,
            )
            raise

        route = get_route_template(Request(scope))
        duration_seconds = time.perf_counter() - start
        _safe_emit_metrics(
            metric_name="http.server.requests.total",
            metric_event="http_request",
            operation=record_http_request,
            method=method,
            route=route,
            status_code=status_code,
        )
        _safe_emit_metrics(
            metric_name="http.server.request.duration",
            metric_event="http_request_duration",
            operation=record_http_request_duration,
            method=method,
            route=route,
            status_code=status_code,
            duration_seconds=duration_seconds,
        )

        if status_code >= 500:
            _safe_emit_metrics(
                metric_name="http.server.errors.total",
                metric_event="http_error",
                operation=record_http_error,
                method=method,
                route=route,
                status_code=status_code,
                error_type="http_5xx",
            )
