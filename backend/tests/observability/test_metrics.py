from __future__ import annotations

from app.core.observability.metrics import (
    record_rate_limit_backend_error,
    record_rate_limit_check_duration,
    record_rate_limit_request,
)


def test_rate_limit_metric_helpers_are_noop_safe() -> None:
    assert (
        record_rate_limit_request(
            policy_name="invite_create",
            result="allowed",
            identifier_kind="user",
        )
        is None
    )
    assert (
        record_rate_limit_backend_error(
            policy_name="invite_create",
            identifier_kind="user",
            error_type="RuntimeError",
        )
        is None
    )
    assert (
        record_rate_limit_check_duration(
            policy_name="invite_create",
            result="allowed",
            identifier_kind="user",
            duration_seconds=0.01,
        )
        is None
    )
