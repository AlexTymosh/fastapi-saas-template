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
    value: str | None,
    *,
    required: bool,
) -> OperationalReasonCode | None:
    """Map legacy free-text reason payloads to a safe persisted reason code.

    Existing clients may still submit the old ``reason`` field. The raw value is
    accepted only as input compatibility and is never returned to service code for
    persistence.
    """

    if value is None:
        if required:
            raise ValueError("reason_code is required")
        return None

    normalised = value.strip()
    if not normalised:
        if required:
            raise ValueError("reason_code is required")
        return None

    try:
        return OperationalReasonCode(normalised)
    except ValueError:
        return OperationalReasonCode.OTHER
