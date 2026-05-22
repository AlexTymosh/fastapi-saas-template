from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

_REASON_MAX_LENGTH = 500

_SENSITIVE_REASON_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b("
        r"password|passwd|pwd|secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|jwt"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+[a-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    re.compile(
        r"\b("
        r"diagnosis|diagnosed|clinical|clinic notes|x-?ray|xray|"
        r"medical|medication|treatment plan|nhs(?:\s+number)?"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:postgres(?:ql)?|mysql|redis|mongodb)://\S+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])"),
)


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


def _contains_sensitive_reason_detail(value: str) -> bool:
    return any(
        pattern.search(value) is not None for pattern in _SENSITIVE_REASON_PATTERNS
    )


def _ensure_reason_has_no_sensitive_detail(value: str) -> None:
    if _contains_sensitive_reason_detail(value):
        raise ValueError(
            "reason must not contain secrets, tokens, contact details, "
            "or clinical/patient details"
        )


def normalise_legacy_reason(
    value: object | None,
    *,
    required: bool,
) -> OperationalReasonCode | None:
    """Map only legacy free-text reason payloads to a safe persisted code.

    This helper is intentionally for the old ``reason`` input field only. New
    ``reason_code`` input must be validated strictly by Pydantic's enum handling
    so typos return 422 instead of being silently persisted as ``other``.

    Legacy free text is discarded and stored as ``other`` only after a narrow
    privacy guard rejects obvious secrets, contact details, and clinical details.
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
        _ensure_reason_has_no_sensitive_detail(normalised)
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
    used after the privacy guard in :func:`normalise_legacy_reason`.
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
