import pytest
from pydantic import ValidationError

from app.audit.reasons import OperationalReasonCode
from app.invites.schemas.invites import RevokeInviteRequest
from app.platform.schemas.platform_organisations import (
    PlatformOrganisationPatchRequest,
)
from app.platform.schemas.platform_users import ReasonRequest


def test_reason_request_requires_structured_reason_code() -> None:
    payload = ReasonRequest(reason_code=OperationalReasonCode.SECURITY_INCIDENT)

    assert payload.reason == "security_incident"


def test_reason_request_schema_marks_reason_code_required() -> None:
    schema = ReasonRequest.model_json_schema(mode="validation")

    assert schema["required"] == ["reason_code"]


def test_legacy_free_text_reason_is_rejected() -> None:
    with pytest.raises(ValidationError, match="structured reason code"):
        ReasonRequest(reason="manual review requested by the account owner")


def test_legacy_reason_can_submit_existing_reason_code_value() -> None:
    payload = ReasonRequest(reason="compliance_review")

    assert payload.reason == "compliance_review"


def test_explicit_reason_code_wins_when_legacy_reason_is_also_present() -> None:
    payload = ReasonRequest(
        reason_code="compliance_review",
        reason="manual review requested by the account owner",
    )

    assert payload.reason == "compliance_review"


def test_null_reason_code_with_structured_legacy_reason_uses_legacy_reason() -> None:
    payload = ReasonRequest(
        reason_code=None,
        reason="other",
    )

    assert payload.reason == "other"


def test_null_reason_code_with_legacy_free_text_is_rejected() -> None:
    with pytest.raises(ValidationError, match="structured reason code"):
        ReasonRequest(
            reason_code=None,
            reason="manual review requested by the account owner",
        )


def test_invalid_explicit_reason_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReasonRequest(reason_code="compliance_reveiw")


def test_missing_required_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReasonRequest()


def test_platform_organisation_patch_uses_reason_code_property() -> None:
    payload = PlatformOrganisationPatchRequest(
        name="Updated",
        reason_code=OperationalReasonCode.DATA_CORRECTION,
    )

    assert payload.reason == "data_correction"


def test_platform_organisation_patch_schema_marks_reason_code_required() -> None:
    schema = PlatformOrganisationPatchRequest.model_json_schema(mode="validation")

    assert schema["required"] == ["reason_code"]


def test_platform_organisation_patch_rejects_invalid_reason_code() -> None:
    with pytest.raises(ValidationError):
        PlatformOrganisationPatchRequest(
            name="Updated",
            reason_code="data_corection",
        )


def test_platform_organisation_patch_accepts_both_reason_fields() -> None:
    payload = PlatformOrganisationPatchRequest(
        name="Updated",
        reason_code="data_correction",
        reason="legacy free text",
    )

    assert payload.reason == "data_correction"


def test_org_patch_uses_structured_legacy_reason_when_code_is_null() -> None:
    payload = PlatformOrganisationPatchRequest(
        name="Updated",
        reason_code=None,
        reason="other",
    )

    assert payload.reason == "other"


def test_org_patch_rejects_free_text_legacy_reason_when_code_is_null() -> None:
    with pytest.raises(ValidationError, match="structured reason code"):
        PlatformOrganisationPatchRequest(
            name="Updated",
            reason_code=None,
            reason="legacy free text",
        )


def test_revoke_invite_reason_code_is_optional_but_structured_when_present() -> None:
    empty_payload = RevokeInviteRequest()
    structured_payload = RevokeInviteRequest(
        reason_code=OperationalReasonCode.COMPLIANCE_REVIEW
    )
    legacy_payload = RevokeInviteRequest(reason="other")

    assert empty_payload.reason is None
    assert structured_payload.reason == "compliance_review"
    assert legacy_payload.reason == "other"


def test_revoke_invite_rejects_legacy_free_text() -> None:
    with pytest.raises(ValidationError, match="structured reason code"):
        RevokeInviteRequest(reason="unstructured operational text")


def test_revoke_invite_rejects_invalid_explicit_reason_code() -> None:
    with pytest.raises(ValidationError):
        RevokeInviteRequest(reason_code="compliance_reveiw")


def test_revoke_invite_accepts_both_reason_fields() -> None:
    payload = RevokeInviteRequest(
        reason_code="compliance_review",
        reason="legacy free text",
    )

    assert payload.reason == "compliance_review"


def test_revoke_invite_uses_structured_legacy_reason_when_reason_code_is_null() -> None:
    payload = RevokeInviteRequest(
        reason_code=None,
        reason="other",
    )

    assert payload.reason == "other"


def test_revoke_invite_rejects_legacy_free_text_when_reason_code_is_null() -> None:
    with pytest.raises(ValidationError, match="structured reason code"):
        RevokeInviteRequest(
            reason_code=None,
            reason="legacy free text",
        )
