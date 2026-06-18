from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import pytest

import app.privacy.erasures.orchestrator as erasure_orchestrator
from app.privacy.erasures.orchestrator import (
    _ErasureSnapshot,
    _provider_result,
    _run_core_providers,
)
from app.privacy.erasures.remaining_inventory import RemainingInventoryErasureStatus
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


class _FakeDecision(StrEnum):
    MINIMISED = "minimised"
    ALREADY_MINIMISED = "already_minimised"
    RETAINED_BY_POLICY = "retained_by_policy"
    MANUAL_REVIEW_POLICY = "manual_review_policy"


@dataclass(frozen=True, slots=True)
class _FakeProviderResult:
    provider_key: str
    table_name: str
    status: object
    affected_rows: int
    changed_fields: tuple[str, ...]


def _result(
    provider_key: str,
    *,
    status: object,
    affected_rows: int = 0,
    changed_fields: tuple[str, ...] = (),
) -> _FakeProviderResult:
    return _FakeProviderResult(
        provider_key=provider_key,
        table_name=provider_key.split(".", maxsplit=1)[0],
        status=status,
        affected_rows=affected_rows,
        changed_fields=changed_fields,
    )


def test_provider_result_preserves_policy_decision_without_mutation() -> None:
    result = _provider_result(
        provider_key="organisations.review_subject_references",
        table_name="organisations",
        decision=RemainingInventoryErasureStatus.MANUAL_REVIEW_POLICY,
        affected_rows=0,
        changed_fields=(),
    )

    assert result.decision == "manual_review_policy"
    assert result.requires_manual_review is True
    assert result.retained_by_policy is False
    assert result.did_mutate is False


def test_provider_result_preserves_retained_policy_decision() -> None:
    result = _provider_result(
        provider_key="memberships.minimise_subject_link",
        table_name="memberships",
        decision=RemainingInventoryErasureStatus.RETAINED_BY_POLICY,
        affected_rows=0,
        changed_fields=(),
    )

    assert result.decision == "retained_by_policy"
    assert result.requires_manual_review is False
    assert result.retained_by_policy is True
    assert result.did_mutate is False


def test_provider_result_preserves_string_decisions() -> None:
    result = _provider_result(
        provider_key="users.anonymise_profile",
        table_name="users",
        decision="already_anonymised",
        affected_rows=0,
        changed_fields=(),
    )

    assert result.decision == "already_anonymised"
    assert result.did_mutate is False


def test_core_provider_runner_preserves_each_provider_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject_user_id = uuid4()
    now = datetime.now(UTC)
    snapshot = _ErasureSnapshot(
        subject_user_id=subject_user_id,
        subject_email="subject@example.com",
        invite_ids=(uuid4(),),
    )

    async def _audit(*args: object, **kwargs: object) -> _FakeProviderResult:
        return _result(
            "audit.minimise_subject_actor_or_target_identifiers",
            status=_FakeDecision.MINIMISED,
            affected_rows=1,
            changed_fields=("actor_user_id",),
        )

    async def _outbox(*args: object, **kwargs: object) -> _FakeProviderResult:
        return _result(
            "outbox.purge_or_scrub_payload",
            status="already_scrubbed",
        )

    async def _invites(*args: object, **kwargs: object) -> _FakeProviderResult:
        return _result(
            "invites.anonymise_or_purge_subject_references",
            status="already_anonymised",
        )

    async def _memberships(
        *args: object,
        **kwargs: object,
    ) -> _FakeProviderResult:
        return _result(
            "memberships.minimise_subject_link",
            status=RemainingInventoryErasureStatus.RETAINED_BY_POLICY,
        )

    async def _organisations(
        *args: object,
        **kwargs: object,
    ) -> _FakeProviderResult:
        return _result(
            "organisations.review_subject_references",
            status=RemainingInventoryErasureStatus.MANUAL_REVIEW_POLICY,
        )

    async def _platform_staff(
        *args: object,
        **kwargs: object,
    ) -> _FakeProviderResult:
        return _result(
            "platform_staff.minimise_subject_or_creator_links",
            status=RemainingInventoryErasureStatus.ALREADY_MINIMISED,
        )

    async def _export_artifacts(
        *args: object,
        **kwargs: object,
    ) -> _FakeProviderResult:
        return _result(
            "export_artifacts.delete_object_minimise_subject_or_actor_metadata",
            status=RemainingInventoryErasureStatus.MINIMISED,
            affected_rows=1,
            changed_fields=("subject_user_id",),
        )

    async def _privacy_governance(
        *args: object,
        **kwargs: object,
    ) -> tuple[_FakeProviderResult, ...]:
        return (
            _result(
                "privacy_governance.minimise_authorizations",
                status=RemainingInventoryErasureStatus.ALREADY_MINIMISED,
            ),
            _result(
                "privacy_governance.minimise_consent_records",
                status=RemainingInventoryErasureStatus.RETAINED_BY_POLICY,
            ),
            _result(
                "privacy_governance.minimise_notice_acceptances",
                status=RemainingInventoryErasureStatus.MINIMISED,
                affected_rows=1,
                changed_fields=("source",),
            ),
        )

    async def _user(*args: object, **kwargs: object) -> _FakeProviderResult:
        return _result(
            "users.anonymise_profile",
            status="anonymised",
            affected_rows=1,
            changed_fields=("email",),
        )

    async def _dsr(*args: object, **kwargs: object) -> _FakeProviderResult:
        return _result(
            "dsr.minimise_workflow_identifiers",
            status=RemainingInventoryErasureStatus.MINIMISED,
            affected_rows=1,
            changed_fields=("subject_user_id",),
        )

    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_audit_events_for_approved_erase_request",
        _audit,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "scrub_outbox_for_approved_erase_request",
        _outbox,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "anonymise_invites_for_approved_erase_request",
        _invites,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "apply_membership_erasure_policy",
        _memberships,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "apply_organisation_erasure_policy",
        _organisations,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_platform_staff_for_approved_erase_request",
        _platform_staff,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_export_artifacts_for_approved_erase_request",
        _export_artifacts,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_privacy_governance_for_approved_erase_request",
        _privacy_governance,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "anonymise_user_profile_for_approved_erase_request",
        _user,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_dsr_workflow_for_approved_erase_request",
        _dsr,
    )

    results = run_async(
        _run_provider_results(
            snapshot=snapshot,
            subject_user_id=subject_user_id,
            now=now,
        )
    )

    decisions_by_key = {result.provider_key: result.decision for result in results}
    assert decisions_by_key["memberships.minimise_subject_link"] == (
        "retained_by_policy"
    )
    assert decisions_by_key["organisations.review_subject_references"] == (
        "manual_review_policy"
    )
    assert decisions_by_key["privacy_governance.minimise_consent_records"] == (
        "retained_by_policy"
    )
    export_artifacts_key = (
        "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
    )
    assert decisions_by_key[export_artifacts_key] == "minimised"


async def _run_provider_results(
    *,
    snapshot: _ErasureSnapshot,
    subject_user_id: UUID,
    now: datetime,
) -> tuple[erasure_orchestrator.ErasureProviderRunResult, ...]:
    return await _run_core_providers(
        object(),
        object(),
        snapshot=snapshot,
        subject_user_id=subject_user_id,
        now=now,
    )
