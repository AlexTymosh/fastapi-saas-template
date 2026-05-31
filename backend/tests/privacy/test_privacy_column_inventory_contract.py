from __future__ import annotations

import pytest

from app.core.db.base import Base
from app.core.db.registry import import_all_models
from app.privacy.column_inventory import (
    PRIVACY_COLUMN_POLICIES,
    get_privacy_column_policies_by_table,
)
from app.privacy.data_inventory import (
    PrivacyFieldClassification,
    get_privacy_inventory_by_table,
)

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


def _model_columns_by_table() -> dict[str, set[str]]:
    import_all_models()
    return {
        table_name: {column.name for column in table.columns}
        for table_name, table in Base.metadata.tables.items()
    }


def test_column_inventory_covers_every_column_for_inventoried_tables() -> None:
    model_columns = _model_columns_by_table()
    table_inventory = get_privacy_inventory_by_table()
    column_policies = get_privacy_column_policies_by_table()

    assert set(column_policies) == set(table_inventory)

    for table_name in table_inventory:
        assert set(column_policies[table_name]) == model_columns[table_name]


def test_column_inventory_preserves_table_field_inventory_contract() -> None:
    table_inventory = get_privacy_inventory_by_table()
    column_policies = get_privacy_column_policies_by_table()

    for table_name, table_entry in table_inventory.items():
        for field in table_entry.fields:
            policy = column_policies[table_name][field.name]
            assert policy.classification == field.classification
            assert policy.export is field.export
            assert policy.erasure_action == field.erasure_action


def test_column_inventory_has_unique_table_column_pairs() -> None:
    pairs = [
        (policy.table_name, policy.column_name) for policy in PRIVACY_COLUMN_POLICIES
    ]

    assert len(pairs) == len(set(pairs))


def test_column_inventory_documents_non_exported_columns() -> None:
    for policy in PRIVACY_COLUMN_POLICIES:
        assert policy.rationale.strip()
        if not policy.export:
            assert len(policy.rationale.strip()) >= 12


def test_column_inventory_never_exports_secrets_or_worker_tokens() -> None:
    secret_policies = [
        policy
        for policy in PRIVACY_COLUMN_POLICIES
        if policy.classification == PrivacyFieldClassification.SECRET_OR_TOKEN
    ]

    assert secret_policies
    for policy in secret_policies:
        assert policy.export is False


def test_column_inventory_blocks_internal_storage_and_payload_fields() -> None:
    policies = get_privacy_column_policies_by_table()

    assert policies["export_artifacts"]["storage_key"].export is False
    assert policies["export_artifacts"]["processing_token"].export is False
    assert policies["outbox_events"]["payload_json"].export is False
    assert policies["data_subject_requests"]["idempotency_key_hash"].export is False
    assert policies["data_subject_requests"]["idempotency_fingerprint"].export is False
