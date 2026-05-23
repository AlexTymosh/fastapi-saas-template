import pytest
from pydantic import ValidationError

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason
from app.invites.schemas.invites import RevokeInviteRequest
from app.platform.schemas.platform_users import ReasonRequest


@pytest.mark.parametrize(
    ("raw_reason", "expected_code"),
    [
        ("security_incident", OperationalReasonCode.SECURITY_INCIDENT),
        (" security_incident ", OperationalReasonCode.SECURITY_INCIDENT),
        ("Legacy operational note without sensitive data", OperationalReasonCode.OTHER),
        ("Manual review requested by the account owner", OperationalReasonCode.OTHER),
    ],
)
def test_legacy_reasons_map_to_safe_codes(
    raw_reason: str,
    expected_code: OperationalReasonCode,
) -> None:
    assert normalise_legacy_reason(raw_reason, required=True) == expected_code


@pytest.mark.parametrize(
    "raw_reason",
    [
        "password reset token was pasted here",
        "Bearer abcdefghijklmnopqrstuvwxyz123456",
        "special category personal data was pasted here",
        "diagnosis details were pasted here",
        "treatment plan details were pasted here",
        "contact jane@example.com about this",
        "postgresql://user:pass@example.test/db",
        "0123456789abcdef0123456789abcdef",
    ],
)
def test_sensitive_legacy_reasons_are_rejected(raw_reason: str) -> None:
    with pytest.raises(ValueError, match="reason must not contain"):
        normalise_legacy_reason(raw_reason, required=True)


def test_required_legacy_reason_still_requires_a_non_blank_value() -> None:
    with pytest.raises(ValueError, match="reason_code is required"):
        normalise_legacy_reason(" ", required=True)


def test_optional_blank_legacy_reason_maps_to_none() -> None:
    assert normalise_legacy_reason(" ", required=False) is None


def test_reason_request_rejects_sensitive_legacy_reason_payload() -> None:
    with pytest.raises(ValidationError, match="reason must not contain"):
        ReasonRequest(reason="contains diagnosis details")


def test_reason_request_preserves_strict_reason_code_validation() -> None:
    with pytest.raises(ValidationError):
        ReasonRequest(reason_code="not_a_valid_reason_code")


def test_invite_revoke_allows_optional_reason_to_be_omitted() -> None:
    request = RevokeInviteRequest()
    assert request.reason is None


def test_invite_revoke_rejects_sensitive_legacy_reason_payload() -> None:
    with pytest.raises(ValidationError, match="reason must not contain"):
        RevokeInviteRequest(reason="access_token abcdefghijklmnopqrstuvwxyz123")
