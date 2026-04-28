from __future__ import annotations

from typing import Final

from app.core.observability.metrics import meter
from app.core.observability.rate_limit_metrics import RATE_LIMIT_ATTRIBUTE_ERROR_TYPE
from app.core.observability.safety import (
    _handle_metric_recording_failure,
    _safe_record_metric,
)

HTTP_REQUESTS_TOTAL = meter.create_counter(
    "http.server.requests.total",
    unit="{request}",
    description="Total number of HTTP server requests.",
)

HTTP_ERRORS_TOTAL = meter.create_counter(
    "http.server.errors.total",
    unit="{error}",
    description="Total number of HTTP server error responses.",
)

HTTP_REQUEST_DURATION = meter.create_histogram(
    "http.server.request.duration",
    unit="s",
    description="Duration of HTTP server requests.",
)

HTTP_ATTRIBUTE_METHOD: Final = "http.request.method"
HTTP_ATTRIBUTE_ROUTE: Final = "http.route"
HTTP_ATTRIBUTE_STATUS_CODE: Final = "http.response.status_code"

ALLOWED_HTTP_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        HTTP_ATTRIBUTE_METHOD,
        HTTP_ATTRIBUTE_ROUTE,
        HTTP_ATTRIBUTE_STATUS_CODE,
    }
)

ALLOWED_HTTP_ERROR_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        *ALLOWED_HTTP_ATTRIBUTE_KEYS,
        RATE_LIMIT_ATTRIBUTE_ERROR_TYPE,
    }
)


def _validate_attribute_keys(
    attributes: dict[str, str | int], allowed_keys: frozenset[str]
) -> None:
    invalid_keys = set(attributes).difference(allowed_keys)
    if invalid_keys:
        keys = ", ".join(sorted(invalid_keys))
        raise ValueError(f"Unsupported metric attribute keys: {keys}")


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
) -> None:
    attributes = {
        HTTP_ATTRIBUTE_METHOD: method,
        HTTP_ATTRIBUTE_ROUTE: route,
        HTTP_ATTRIBUTE_STATUS_CODE: status_code,
    }
    try:
        _validate_attribute_keys(attributes, ALLOWED_HTTP_ATTRIBUTE_KEYS)
    except Exception as exc:
        _handle_metric_recording_failure(
            metric_name="http.server.requests.total",
            metric_event="http_request",
            reason=exc.__class__.__name__,
        )
        return

    _safe_record_metric(
        HTTP_REQUESTS_TOTAL.add,
        1,
        attributes=attributes,
        metric_name="http.server.requests.total",
        metric_event="http_request",
    )


def record_http_error(
    *,
    method: str,
    route: str,
    status_code: int,
    error_type: str,
) -> None:
    attributes = {
        HTTP_ATTRIBUTE_METHOD: method,
        HTTP_ATTRIBUTE_ROUTE: route,
        HTTP_ATTRIBUTE_STATUS_CODE: status_code,
        RATE_LIMIT_ATTRIBUTE_ERROR_TYPE: error_type,
    }
    try:
        _validate_attribute_keys(attributes, ALLOWED_HTTP_ERROR_ATTRIBUTE_KEYS)
    except Exception as exc:
        _handle_metric_recording_failure(
            metric_name="http.server.errors.total",
            metric_event="http_error",
            reason=exc.__class__.__name__,
        )
        return
    _safe_record_metric(
        HTTP_ERRORS_TOTAL.add,
        1,
        attributes=attributes,
        metric_name="http.server.errors.total",
        metric_event="http_error",
    )


def record_http_request_duration(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    attributes = {
        HTTP_ATTRIBUTE_METHOD: method,
        HTTP_ATTRIBUTE_ROUTE: route,
        HTTP_ATTRIBUTE_STATUS_CODE: status_code,
    }
    try:
        _validate_attribute_keys(attributes, ALLOWED_HTTP_ATTRIBUTE_KEYS)
    except Exception as exc:
        _handle_metric_recording_failure(
            metric_name="http.server.request.duration",
            metric_event="http_request_duration",
            reason=exc.__class__.__name__,
        )
        return
    _safe_record_metric(
        HTTP_REQUEST_DURATION.record,
        duration_seconds,
        attributes=attributes,
        metric_name="http.server.request.duration",
        metric_event="http_request_duration",
    )
