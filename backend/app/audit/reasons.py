from __future__ import annotations

from enum import StrEnum
from typing import Any

_REASON_MAX_LENGTH = 500


class OperationalReasonCode(StrEnum):
    """Structured operational reasons safe to persist in audit/status fields."""

    SECURITY_INCIDENT = "security_incident"
    COMPLIANCE_REVIEW = "compliance_review"
    POLICY_VIOLATION = "policy_violation"
    USER_REQUEST = "user_request"
    ACCOUNT_COMPROMISE = "account_compromise"
    BILLING_RISK = "billing_risk"
    DATA_CORRECTION = "data_correction"
    DUPLICATE_OR_ERROR = "duplicate_or_error"
    OPERATIONAL_MAINTENANCE = "operational_maintenance"
    OTHER = "other"


def normalise_legacy_reason(
    value: object | None,
    *,
    required: bool,
) -> OperationalReasonCode | None:
    """Map only legacy free-text reason payloads to a safe persisted code.

    This helper is intentionally for the old ``reason`` input field only. New
    ``reason_code`` input must be validated strictly by Pydantic's enum handling
    so typos return 422 instead of being silently persisted as ``other``.
    """

    if isinstance(value, OperationalReasonCode):
        return value

    if value is None:
        if required:
            raise ValueError("reason_code is required")
        return None

    if not isinstance(value, str):
        raise ValueError("reason must be a string")

    normalised = value.strip()
    if not normalised:
        if required:
            raise ValueError("reason_code is required")
        return None

    if len(normalised) > _REASON_MAX_LENGTH:
        raise ValueError("reason must be at most 500 characters")

    try:
        return OperationalReasonCode(normalised)
    except ValueError:
        return OperationalReasonCode.OTHER


def normalise_legacy_reason_payload(
    data: Any,
    *,
    required: bool,
) -> Any:
    """Translate legacy ``reason`` payloads before normal model validation.

    Explicit non-null ``reason_code`` input is preserved so invalid enum values
    are rejected normally with 422. Legacy ``reason`` is always removed before
    ``extra='forbid'`` validation. If a compatibility serializer sends
    ``reason_code: null`` together with legacy ``reason``, the legacy value is
    used.
    """

    if not isinstance(data, dict):
        return data

    has_reason = "reason" in data
    has_reason_code = "reason_code" in data

    if not has_reason:
        return data

    updated = dict(data)
    legacy_reason = updated.pop("reason")

    if has_reason_code and updated.get("reason_code") is not None:
        return updated

    updated["reason_code"] = normalise_legacy_reason(
        legacy_reason,
        required=required,
    )
    return updated
