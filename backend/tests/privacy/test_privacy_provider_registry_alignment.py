from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.privacy.data_inventory import PRIVACY_DATA_INVENTORY
from app.privacy.erasures import orchestrator as erasure_orchestrator
from app.privacy.erasures.coverage import ERASURE_COVERAGE_MAP
from app.privacy.exporters.subject_data import _EXPORT_PROVIDER_TYPES
from app.privacy.provider_keys import (
    erasure_orchestration_provider_order,
    erasure_provider_keys,
    erasure_provider_table_name,
    export_provider_keys,
    export_provider_order,
    export_provider_table_name,
)
from app.privacy.providers.registry import build_privacy_provider_registry
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


@dataclass(frozen=True, slots=True)
class _FakeErasureProviderResult:
    provider_key: str
    table_name: str
    status: str = "minimised"
    affected_rows: int = 0
    changed_fields: tuple[str, ...] = ()


def test_inventory_provider_keys_match_central_catalogues() -> None:
    inventory_export_keys = {
        entry.export_provider_key for entry in PRIVACY_DATA_INVENTORY
    }
    inventory_erasure_keys = {
        entry.erasure_provider_key
        for entry in PRIVACY_DATA_INVENTORY
        if entry.erasure_provider_key is not None
    }

    assert inventory_export_keys == export_provider_keys()
    assert inventory_erasure_keys == erasure_provider_keys()


def test_inventory_provider_tables_match_central_catalogues() -> None:
    for entry in PRIVACY_DATA_INVENTORY:
        assert export_provider_table_name(entry.export_provider_key) == entry.table_name

        if entry.erasure_provider_key is not None:
            assert erasure_provider_table_name(entry.erasure_provider_key) == (
                entry.table_name
            )


def test_runtime_export_provider_order_matches_central_catalogue() -> None:
    runtime_export_keys = tuple(
        provider_type.provider_key for provider_type in _EXPORT_PROVIDER_TYPES
    )

    assert runtime_export_keys == export_provider_order()
    assert set(runtime_export_keys) == export_provider_keys()


def test_runtime_export_provider_tables_match_central_catalogue() -> None:
    for provider_type in _EXPORT_PROVIDER_TYPES:
        assert export_provider_table_name(provider_type.provider_key) == (
            provider_type.table_name
        )


def test_privacy_provider_registry_matches_central_catalogues() -> None:
    registry = build_privacy_provider_registry()
    expected_keys = export_provider_keys() | erasure_provider_keys()

    assert set(registry) == expected_keys

    for provider_key, entry in registry.items():
        if provider_key in export_provider_keys():
            assert export_provider_table_name(provider_key) == entry.table_name
            continue

        assert erasure_provider_table_name(provider_key) == entry.table_name


def test_erasure_coverage_matches_central_catalogue() -> None:
    assert set(ERASURE_COVERAGE_MAP) == erasure_provider_keys()


def test_actual_erasure_provider_result_order_matches_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_provider_keys: list[str] = []

    def fake_provider(provider_key: str):
        async def _run(*args: object, **kwargs: object) -> _FakeErasureProviderResult:
            observed_provider_keys.append(provider_key)
            return _fake_erasure_provider_result(provider_key)

        return _run

    async def fake_privacy_governance_provider(
        *args: object,
        **kwargs: object,
    ) -> tuple[_FakeErasureProviderResult, ...]:
        provider_keys = (
            "privacy_governance.minimise_authorizations",
            "privacy_governance.minimise_consent_records",
            "privacy_governance.minimise_notice_acceptances",
        )
        observed_provider_keys.extend(provider_keys)
        return tuple(
            _fake_erasure_provider_result(provider_key)
            for provider_key in provider_keys
        )

    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_audit_events_for_approved_erase_request",
        fake_provider("audit.minimise_subject_actor_or_target_identifiers"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "scrub_outbox_for_approved_erase_request",
        fake_provider("outbox.purge_or_scrub_payload"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "anonymise_invites_for_approved_erase_request",
        fake_provider("invites.anonymise_or_purge_subject_references"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "apply_membership_erasure_policy",
        fake_provider("memberships.minimise_subject_link"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "apply_organisation_erasure_policy",
        fake_provider("organisations.review_subject_references"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_platform_staff_for_approved_erase_request",
        fake_provider("platform_staff.minimise_subject_or_creator_links"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_export_artifacts_for_approved_erase_request",
        fake_provider(
            "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
        ),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_privacy_governance_for_approved_erase_request",
        fake_privacy_governance_provider,
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "anonymise_user_profile_for_approved_erase_request",
        fake_provider("users.anonymise_profile"),
    )
    monkeypatch.setattr(
        erasure_orchestrator,
        "minimise_dsr_workflow_for_approved_erase_request",
        fake_provider("dsr.minimise_workflow_identifiers"),
    )

    subject_user_id = uuid4()
    request = SimpleNamespace(id=uuid4(), subject_user_id=subject_user_id)
    snapshot = erasure_orchestrator._ErasureSnapshot(
        subject_user_id=subject_user_id,
        subject_email="subject@example.com",
        invite_ids=(),
    )

    provider_results = run_async(
        erasure_orchestrator._run_core_providers(
            None,
            request,
            snapshot=snapshot,
            subject_user_id=subject_user_id,
            now=datetime(2026, 7, 11, tzinfo=UTC),
        )
    )
    result_provider_keys = tuple(result.provider_key for result in provider_results)

    assert tuple(observed_provider_keys) == erasure_orchestration_provider_order()
    assert result_provider_keys == erasure_orchestration_provider_order()
    assert set(result_provider_keys) == erasure_provider_keys()


def _fake_erasure_provider_result(provider_key: str) -> _FakeErasureProviderResult:
    return _FakeErasureProviderResult(
        provider_key=provider_key,
        table_name=erasure_provider_table_name(provider_key),
    )
