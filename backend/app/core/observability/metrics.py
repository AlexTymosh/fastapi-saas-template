from __future__ import annotations

from typing import Final

from fastapi import Request
from opentelemetry import metrics

METER_NAME: Final = "fastapi_saas_template"

RATE_LIMIT_DECISION_ATTRIBUTES: Final[tuple[str, ...]] = (
    "rate_limit.policy",
    "rate_limit.result",
    "rate_limit.identifier_kind",
)
RATE_LIMIT_BACKEND_ERROR_ATTRIBUTES: Final[tuple[str, ...]] = (
    "rate_limit.policy",
    "rate_limit.identifier_kind",
    "error.type",
)
RATE_LIMIT_DURATION_ATTRIBUTES: Final[tuple[str, ...]] = (
    "rate_limit.policy",
    "rate_limit.result",
    "rate_limit.identifier_kind",
)
FORBIDDEN_METRIC_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "user_id",
        "email",
        "organisation_id",
        "request_id",
        "trace_id",
        "path",
        "raw_path",
        "url",
        "ip",
        "client_ip",
        "token",
        "redis_key",
        "identifier",
        "identifier_value",
        "hashed_identifier",
    }
)

meter = metrics.get_meter(METER_NAME)

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


def _ensure_safe_attribute_keys(
    attributes: dict[str, str], allowed: tuple[str, ...]
) -> None:
    unknown_keys = set(attributes) - set(allowed)
    if unknown_keys:
        raise ValueError(f"Unsupported metric attribute keys: {sorted(unknown_keys)}")

    forbidden_keys = set(attributes) & FORBIDDEN_METRIC_ATTRIBUTE_KEYS
    if forbidden_keys:
        raise ValueError(f"Forbidden metric attribute keys: {sorted(forbidden_keys)}")


def record_rate_limit_decision(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
) -> None:
    attributes = {
        "rate_limit.policy": policy_name,
        "rate_limit.result": result,
        "rate_limit.identifier_kind": identifier_kind,
    }
    _ensure_safe_attribute_keys(attributes, RATE_LIMIT_DECISION_ATTRIBUTES)
    rate_limit_requests_total.add(1, attributes=attributes)


def record_rate_limit_backend_error(
    *,
    policy_name: str,
    identifier_kind: str,
    error_type: str,
) -> None:
    attributes = {
        "rate_limit.policy": policy_name,
        "rate_limit.identifier_kind": identifier_kind,
        "error.type": error_type,
    }
    _ensure_safe_attribute_keys(attributes, RATE_LIMIT_BACKEND_ERROR_ATTRIBUTES)
    rate_limit_backend_errors_total.add(1, attributes=attributes)


def record_rate_limit_check_duration(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
    duration_seconds: float,
) -> None:
    attributes = {
        "rate_limit.policy": policy_name,
        "rate_limit.result": result,
        "rate_limit.identifier_kind": identifier_kind,
    }
    _ensure_safe_attribute_keys(attributes, RATE_LIMIT_DURATION_ATTRIBUTES)
    rate_limit_check_duration.record(duration_seconds, attributes=attributes)


def get_route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return "unknown"
