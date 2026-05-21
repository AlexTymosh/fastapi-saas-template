from __future__ import annotations

from enum import StrEnum


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
    """Map submitted reason payloads to a safe persisted reason code.

    New clients should submit ``reason_code``. Existing clients may still submit
    the old ``reason`` field, but arbitrary free text is accepted only as input
    compatibility and is never returned to service code for persistence.
    """

    if isinstance(value, OperationalReasonCode):
        return value

    if value is None:
        if required:
            raise ValueError("reason_code is required")
        return None

    if not isinstance(value, str):
        raise ValueError("reason_code must be a string")

    normalised = value.strip()
    if not normalised:
        if required:
            raise ValueError("reason_code is required")
        return None

    try:
        return OperationalReasonCode(normalised)
    except ValueError:
        return OperationalReasonCode.OTHER
