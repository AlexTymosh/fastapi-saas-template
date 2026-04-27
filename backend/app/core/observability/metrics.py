from __future__ import annotations

from typing import Final

from fastapi import Request
from opentelemetry import metrics

meter = metrics.get_meter("fastapi_saas_template")

rate_limit_requests_total = meter.create_counter(
    "rate_limit.requests.total",
    unit="{request}",
    description="Rate limit decisions by policy and result.",
)

rate_limit_backend_errors_total = meter.create_counter(
    "rate_limit.backend_errors.total",
    unit="{error}",
    description="Rate limiter backend errors.",
)

rate_limit_check_duration = meter.create_histogram(
    "rate_limit.check.duration",
    unit="s",
    description="Duration of rate limiter checks.",
)

http_server_requests_total = meter.create_counter(
    "http.server.requests.total",
    unit="{request}",
    description="Total number of HTTP server requests.",
)

http_server_errors_total = meter.create_counter(
    "http.server.errors.total",
    unit="{error}",
    description="Total number of HTTP server error responses.",
)

http_server_request_duration = meter.create_histogram(
    "http.server.request.duration",
    unit="s",
    description="Duration of HTTP server requests.",
)

RATE_LIMIT_RESULT_ALLOWED: Final = "allowed"
RATE_LIMIT_RESULT_BLOCKED: Final = "blocked"
RATE_LIMIT_RESULT_BACKEND_ERROR: Final = "backend_error"
RATE_LIMIT_RESULT_FAIL_OPEN: Final = "fail_open"

ALLOWED_RATE_LIMIT_RESULTS: Final[frozenset[str]] = frozenset(
    {
        RATE_LIMIT_RESULT_ALLOWED,
        RATE_LIMIT_RESULT_BLOCKED,
        RATE_LIMIT_RESULT_BACKEND_ERROR,
        RATE_LIMIT_RESULT_FAIL_OPEN,
    }
)

RATE_LIMIT_ATTRIBUTE_POLICY: Final = "rate_limit.policy"
RATE_LIMIT_ATTRIBUTE_RESULT: Final = "rate_limit.result"
RATE_LIMIT_ATTRIBUTE_IDENTIFIER_KIND: Final = "rate_limit.identifier_kind"
RATE_LIMIT_ATTRIBUTE_ERROR_TYPE: Final = "error.type"

ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        RATE_LIMIT_ATTRIBUTE_POLICY,
        RATE_LIMIT_ATTRIBUTE_RESULT,
        RATE_LIMIT_ATTRIBUTE_IDENTIFIER_KIND,
        RATE_LIMIT_ATTRIBUTE_ERROR_TYPE,
    }
)

HTTP_ATTRIBUTE_METHOD: Final = "http.request.method"
HTTP_ATTRIBUTE_ROUTE: Final = "http.route"
HTTP_ATTRIBUTE_STATUS_CODE: Final = "http.response.status_code"
HTTP_ATTRIBUTE_ERROR_TYPE: Final = "error.type"

ALLOWED_HTTP_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        HTTP_ATTRIBUTE_METHOD,
        HTTP_ATTRIBUTE_ROUTE,
        HTTP_ATTRIBUTE_STATUS_CODE,
        HTTP_ATTRIBUTE_ERROR_TYPE,
    }
)


def _validate_attribute_keys(attributes: dict[str, str]) -> None:
    invalid_keys = set(attributes).difference(ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS)
    if invalid_keys:
        keys = ", ".join(sorted(invalid_keys))
        raise ValueError(f"Unsupported metric attribute keys: {keys}")


def _validate_result(result: str) -> None:
    if result not in ALLOWED_RATE_LIMIT_RESULTS:
        allowed = ", ".join(sorted(ALLOWED_RATE_LIMIT_RESULTS))
        raise ValueError(
            f"Unsupported rate limit result '{result}'. Allowed: {allowed}"
        )


def record_rate_limit_decision(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
) -> None:
    _validate_result(result)
    attributes = {
        RATE_LIMIT_ATTRIBUTE_POLICY: policy_name,
        RATE_LIMIT_ATTRIBUTE_RESULT: result,
        RATE_LIMIT_ATTRIBUTE_IDENTIFIER_KIND: identifier_kind,
    }
    _validate_attribute_keys(attributes)
    rate_limit_requests_total.add(1, attributes=attributes)


def record_rate_limit_backend_error(
    *,
    policy_name: str,
    identifier_kind: str,
    error_type: str,
) -> None:
    attributes = {
        RATE_LIMIT_ATTRIBUTE_POLICY: policy_name,
        RATE_LIMIT_ATTRIBUTE_IDENTIFIER_KIND: identifier_kind,
        RATE_LIMIT_ATTRIBUTE_ERROR_TYPE: error_type,
    }
    _validate_attribute_keys(attributes)
    rate_limit_backend_errors_total.add(1, attributes=attributes)


def record_rate_limit_check_duration(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
    duration_seconds: float,
) -> None:
    _validate_result(result)
    attributes = {
        RATE_LIMIT_ATTRIBUTE_POLICY: policy_name,
        RATE_LIMIT_ATTRIBUTE_RESULT: result,
        RATE_LIMIT_ATTRIBUTE_IDENTIFIER_KIND: identifier_kind,
    }
    _validate_attribute_keys(attributes)
    rate_limit_check_duration.record(duration_seconds, attributes=attributes)


def get_route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return "unknown"


def _validate_http_attribute_keys(attributes: dict[str, str | int]) -> None:
    invalid_keys = set(attributes).difference(ALLOWED_HTTP_ATTRIBUTE_KEYS)
    if invalid_keys:
        keys = ", ".join(sorted(invalid_keys))
        raise ValueError(f"Unsupported HTTP metric attribute keys: {keys}")


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
) -> None:
    attributes: dict[str, str | int] = {
        HTTP_ATTRIBUTE_METHOD: method,
        HTTP_ATTRIBUTE_ROUTE: route,
        HTTP_ATTRIBUTE_STATUS_CODE: status_code,
    }
    _validate_http_attribute_keys(attributes)
    http_server_requests_total.add(1, attributes=attributes)


def record_http_error(
    *,
    method: str,
    route: str,
    status_code: int,
    error_type: str,
) -> None:
    attributes: dict[str, str | int] = {
        HTTP_ATTRIBUTE_METHOD: method,
        HTTP_ATTRIBUTE_ROUTE: route,
        HTTP_ATTRIBUTE_STATUS_CODE: status_code,
        HTTP_ATTRIBUTE_ERROR_TYPE: error_type,
    }
    _validate_http_attribute_keys(attributes)
    http_server_errors_total.add(1, attributes=attributes)


def record_http_request_duration(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    attributes: dict[str, str | int] = {
        HTTP_ATTRIBUTE_METHOD: method,
        HTTP_ATTRIBUTE_ROUTE: route,
        HTTP_ATTRIBUTE_STATUS_CODE: status_code,
    }
    _validate_http_attribute_keys(attributes)
    http_server_request_duration.record(duration_seconds, attributes=attributes)
