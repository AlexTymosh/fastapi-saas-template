from __future__ import annotations


def record_rate_limit_request(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
) -> None:
    _ = (policy_name, result, identifier_kind)


def record_rate_limit_backend_error(
    *,
    policy_name: str,
    identifier_kind: str,
    error_type: str,
) -> None:
    _ = (policy_name, identifier_kind, error_type)


def record_rate_limit_check_duration(
    *,
    policy_name: str,
    result: str,
    identifier_kind: str,
    duration_seconds: float,
) -> None:
    _ = (policy_name, result, identifier_kind, duration_seconds)
