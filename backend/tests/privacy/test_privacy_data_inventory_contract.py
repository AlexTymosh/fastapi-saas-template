from __future__ import annotations

from importlib import import_module

import pytest

from app.core.db.base import Base
from app.core.db.registry import import_all_models
from app.privacy.data_inventory import (
    DSR_SCOPE_EXCLUDED_TABLES,
    ISSUE_328_CORE_TABLES,
    PRIVACY_DATA_INVENTORY,
    PrivacyErasureStrategy,
    get_dsr_scope_exclusions_by_table,
    get_privacy_inventory_by_table,
    get_privacy_provider_keys,
)
from app.privacy.providers.registry import build_privacy_provider_registry

pytestmark = [pytest.mark.privacy, pytest.mark.contract]

_ALLOWED_RETAIN_ONLY_STRATEGIES = {
    PrivacyErasureStrategy.RETAIN_AND_MINIMISE,
    PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
}


def _metadata_table_names() -> set[str]:
    import_all_models()
    return set(Base.metadata.tables)


def _raw_inventory_provider_keys() -> list[str]:
    keys: list[str] = []
    for entry in PRIVACY_DATA_INVENTORY:
        keys.append(entry.export_provider_key)
        if entry.erasure_provider_key is not None:
            keys.append(entry.erasure_provider_key)
    return keys


def test_privacy_inventory_accounts_for_all_current_model_tables() -> None:
    table_names = _metadata_table_names()
    inventoried = set(get_privacy_inventory_by_table())
    excluded = set(get_dsr_scope_exclusions_by_table())

    assert table_names - inventoried - excluded == set()
    assert inventoried - table_names == set()
    assert excluded - table_names == set()


def test_scope_exclusions_are_explicit_and_reasoned() -> None:
    exclusions = DSR_SCOPE_EXCLUDED_TABLES

    assert exclusions
    for exclusion in exclusions:
        assert exclusion.table_name
        assert len(exclusion.reason.strip()) >= 20


def test_issue_328_core_tables_have_export_and_erasure_coverage() -> None:
    inventory = get_privacy_inventory_by_table()

    missing_core_tables = ISSUE_328_CORE_TABLES - set(inventory)
    assert missing_core_tables == set()

    for table_name in ISSUE_328_CORE_TABLES:
        entry = inventory[table_name]
        assert entry.export_provider_key
        assert entry.fields
        assert entry.erasure_strategy != PrivacyErasureStrategy.NOT_APPLICABLE
        if entry.erasure_provider_key is None:
            assert entry.erasure_strategy in _ALLOWED_RETAIN_ONLY_STRATEGIES


def test_invite_inventory_exports_relationship_context() -> None:
    inventory = get_privacy_inventory_by_table()
    invite_fields = {field.name: field for field in inventory["invites"].fields}

    assert invite_fields["organisation_id"].export is True
    assert invite_fields["role"].export is True
    assert invite_fields["organisation_id"].erasure_action.name == "RETAIN_MINIMISED"
    assert invite_fields["role"].erasure_action.name == "RETAIN_MINIMISED"
    assert invite_fields["token_hash"].export is False


def test_subject_locators_cover_actor_side_identifiers() -> None:
    inventory = get_privacy_inventory_by_table()

    invite_locator = inventory["invites"].subject_locator
    assert "email" in invite_locator
    assert "revoked_by_user_id" in invite_locator

    platform_staff_locator = inventory["platform_staff"].subject_locator
    assert "user_id" in platform_staff_locator
    assert "created_by_user_id" in platform_staff_locator

    export_artifacts_locator = inventory["export_artifacts"].subject_locator
    assert "subject_user_id" in export_artifacts_locator
    assert "requester_user_id" in export_artifacts_locator
    assert "requested_by_user_id" in export_artifacts_locator
    assert "generated_by_user_id" in export_artifacts_locator


def test_audit_subject_locator_covers_target_type_joins() -> None:
    inventory = get_privacy_inventory_by_table()
    audit_locator = inventory["audit_events"].subject_locator

    assert "actor_user_id" in audit_locator
    assert "target_type='user'" in audit_locator
    assert "privacy_consent" in audit_locator
    assert "privacy_notice" in audit_locator
    assert "target_type='invite'" in audit_locator
    assert "invites.email" in audit_locator
    assert "invites.revoked_by_user_id" in audit_locator
    assert "target_type='membership'" in audit_locator
    assert "memberships.user_id" in audit_locator
    assert "target_type='data_subject_request'" in audit_locator
    assert "data_subject_requests.id" in audit_locator
    assert "reviewer_user_id" in audit_locator
    assert "target_type='export_artifact'" in audit_locator
    assert "export_artifacts.id" in audit_locator
    assert "generated_by_user_id" in audit_locator
    assert "target_type='platform_staff'" in audit_locator
    assert "created_by_user_id" in audit_locator


def test_inventory_entries_are_unique_and_have_required_contract_fields() -> None:
    table_names = [entry.table_name for entry in PRIVACY_DATA_INVENTORY]
    raw_provider_keys = _raw_inventory_provider_keys()

    assert len(table_names) == len(set(table_names))
    assert len(raw_provider_keys) == len(set(raw_provider_keys))
    assert set(raw_provider_keys) == get_privacy_provider_keys()

    for entry in PRIVACY_DATA_INVENTORY:
        assert entry.model_module.startswith("app.")
        assert entry.model_name
        assert entry.subject_locator
        assert entry.data_categories
        assert entry.fields
        assert entry.export_provider_key
        assert entry.retention_policy_key
        assert entry.notes

        for field in entry.fields:
            assert field.name
            assert field.classification
            assert isinstance(field.export, bool)
            assert field.erasure_action
            assert field.notes


def test_inventory_model_references_match_sqlalchemy_models() -> None:
    for entry in PRIVACY_DATA_INVENTORY:
        module = import_module(entry.model_module)
        model = getattr(module, entry.model_name)

        assert model.__tablename__ == entry.table_name


def test_provider_registry_is_derived_from_inventory() -> None:
    registry = build_privacy_provider_registry()
    expected_keys = get_privacy_provider_keys()

    assert set(registry) == expected_keys
    for provider_key, provider_entry in registry.items():
        inventory_entry = get_privacy_inventory_by_table()[provider_entry.table_name]
        assert provider_key in {
            inventory_entry.export_provider_key,
            inventory_entry.erasure_provider_key,
        }
        assert (
            provider_entry.retention_policy_key == inventory_entry.retention_policy_key
        )
