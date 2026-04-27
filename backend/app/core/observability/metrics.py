from __future__ import annotations

from opentelemetry import metrics

meter = metrics.get_meter("app.core.observability")

_rate_limit_requests_total = meter.create_counter(
    name="rate_limit.requests.total",
    description="Total number of evaluated rate limit requests.",
    unit="1",
)

_rate_limit_backend_errors_total = meter.create_counter(
    name="rate_limit.backend_errors.total",
    description="Total number of rate limiter backend errors.",
    unit="1",
)

_rate_limit_check_duration = meter.create_histogram(
    name="rate_limit.check.duration",
    description="Duration of rate limiter checks in seconds.",
    unit="s",
)


def record_rate_limit_request(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
) -> None:
    _rate_limit_requests_total.add(
        1,
        attributes={
            "rate_limit.policy": policy_name,
            "rate_limit.result": result,
            "rate_limit.identifier_kind": identifier_kind,
        },
    )


def record_rate_limit_backend_error(
    *,
    policy_name: str,
    identifier_kind: str,
    error_type: str,
) -> None:
    _rate_limit_backend_errors_total.add(
        1,
        attributes={
            "rate_limit.policy": policy_name,
            "rate_limit.identifier_kind": identifier_kind,
            "error.type": error_type,
        },
    )


def record_rate_limit_check_duration(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
    duration_seconds: float,
) -> None:
    _rate_limit_check_duration.record(
        duration_seconds,
        attributes={
            "rate_limit.policy": policy_name,
            "rate_limit.result": result,
            "rate_limit.identifier_kind": identifier_kind,
        },
    )
