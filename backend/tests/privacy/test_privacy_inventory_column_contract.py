from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from app.privacy.data_inventory import (
    PRIVACY_DATA_INVENTORY,
    PrivacyFieldClassification,
    PrivacyFieldErasureAction,
    PrivacyTableInventoryEntry,
    get_privacy_inventory_by_table,
)

pytestmark = [pytest.mark.privacy, pytest.mark.contract]

_SUBJECT_OR_JOIN_FIELDS_BY_TABLE = {
    "users": {"id", "external_auth_id", "email"},
    "memberships": {"user_id", "organisation_id", "role"},
    "organisations": {"name", "slug"},
    "invites": {"email", "organisation_id", "role", "revoked_by_user_id"},
    "outbox_events": {"payload_json", "aggregate_id", "last_error"},
    "audit_events": {
        "actor_user_id",
        "target_type",
        "target_id",
        "reason",
        "metadata_json",
        "ip_address",
        "user_agent",
    },
    "platform_staff": {"user_id", "created_by_user_id", "suspended_reason"},
    "data_subject_requests": {
        "requester_user_id",
        "subject_user_id",
        "reviewer_user_id",
        "requester_note",
        "internal_note",
        "idempotency_key_hash",
        "idempotency_fingerprint",
        "execution_failure_reason_code",
        "execution_failure_detail",
        "idempotency_key_expires_at",
    },
    "export_artifacts": {
        "subject_user_id",
        "requester_user_id",
        "requested_by_user_id",
        "generated_by_user_id",
        "processing_token",
        "storage_key",
        "failure_reason_code",
        "failure_detail",
    },
    "data_processing_authorizations": {"subject_user_id", "purpose_id", "source"},
    "consent_records": {
        "subject_user_id",
        "purpose_id",
        "privacy_notice_version",
        "withdrawal_reason_code",
    },
    "privacy_notice_acceptances": {"subject_user_id", "notice_version", "source"},
}

_HIGH_RISK_EXACT_COLUMN_NAMES = {
    "email",
    "external_auth_id",
    "token_hash",
    "payload_json",
    "last_error",
    "reason",
    "metadata_json",
    "ip_address",
    "user_agent",
    "storage_key",
    "processing_token",
    "requester_note",
    "internal_note",
    "suspended_reason",
    "failure_reason_code",
    "failure_detail",
    "execution_failure_detail",
    "idempotency_key_hash",
    "idempotency_fingerprint",
    "idempotency_key_expires_at",
}
_HIGH_RISK_NAME_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "idempotency",
    "reason",
    "detail",
)
_SENSITIVE_NON_EXPORT_COLUMNS = {
    "token_hash",
    "payload_json",
    "last_error",
    "storage_key",
    "processing_token",
    "failure_detail",
    "execution_failure_detail",
    "idempotency_key_hash",
    "idempotency_fingerprint",
    "idempotency_key_expires_at",
}
_SENSITIVE_NON_EXPORT_ACTIONS = {
    PrivacyFieldErasureAction.DELETE,
    PrivacyFieldErasureAction.REMOVE_PAYLOAD_VALUE,
    PrivacyFieldErasureAction.REVIEW_REQUIRED,
}
_SENSITIVE_COLUMN_ALLOWED_CLASSIFICATIONS = {
    "token_hash": {PrivacyFieldClassification.SECRET_OR_TOKEN},
    "processing_token": {PrivacyFieldClassification.SECRET_OR_TOKEN},
    "payload_json": {PrivacyFieldClassification.STRUCTURED_METADATA},
    "last_error": {PrivacyFieldClassification.OPERATIONAL_REASON},
    "storage_key": {PrivacyFieldClassification.INDIRECT_IDENTIFIER},
    "failure_detail": {PrivacyFieldClassification.OPERATIONAL_REASON},
    "execution_failure_detail": {PrivacyFieldClassification.OPERATIONAL_REASON},
    "idempotency_key_hash": {PrivacyFieldClassification.SECRET_OR_TOKEN},
    "idempotency_fingerprint": {PrivacyFieldClassification.SECRET_OR_TOKEN},
    "idempotency_key_expires_at": {PrivacyFieldClassification.LIFECYCLE},
}


def _model_for(entry: PrivacyTableInventoryEntry) -> type[Any]:
    module = import_module(entry.model_module)
    return getattr(module, entry.model_name)


def _table_columns(entry: PrivacyTableInventoryEntry) -> set[str]:
    return set(_model_for(entry).__table__.columns.keys())


def _declared_field_names(entry: PrivacyTableInventoryEntry) -> set[str]:
    return {field.name for field in entry.fields}


def _is_high_risk_column(column_name: str) -> bool:
    return column_name in _HIGH_RISK_EXACT_COLUMN_NAMES or any(
        fragment in column_name for fragment in _HIGH_RISK_NAME_FRAGMENTS
    )


def test_declared_privacy_inventory_fields_exist_on_model_tables() -> None:
    missing_columns: list[str] = []

    for entry in PRIVACY_DATA_INVENTORY:
        table_columns = _table_columns(entry)
        for field_name in sorted(_declared_field_names(entry) - table_columns):
            missing_columns.append(f"{entry.table_name}.{field_name}")

    assert missing_columns == []


def test_subject_or_join_fields_are_declared_when_present_on_table() -> None:
    inventory = get_privacy_inventory_by_table()
    missing_fields: list[str] = []

    for table_name, expected_fields in _SUBJECT_OR_JOIN_FIELDS_BY_TABLE.items():
        entry = inventory[table_name]
        table_columns = _table_columns(entry)
        declared_fields = _declared_field_names(entry)
        present_expected_fields = expected_fields & table_columns

        for field_name in sorted(present_expected_fields - declared_fields):
            missing_fields.append(f"{table_name}.{field_name}")

    assert missing_fields == []


def test_high_risk_columns_are_explicitly_classified_or_out_of_scope() -> None:
    missing: list[str] = []

    for entry in PRIVACY_DATA_INVENTORY:
        table_columns = _table_columns(entry)
        declared_fields = _declared_field_names(entry)
        high_risk_columns = {
            column_name
            for column_name in table_columns
            if _is_high_risk_column(column_name)
        }
        for field_name in sorted(high_risk_columns - declared_fields):
            missing.append(f"{entry.table_name}.{field_name}")

    assert missing == []


def test_sensitive_payload_and_token_columns_are_not_exported_raw() -> None:
    unsafe_exports: list[str] = []
    unsafe_actions: list[str] = []
    unsafe_classifications: list[str] = []

    for entry in PRIVACY_DATA_INVENTORY:
        for field in entry.fields:
            if field.name not in _SENSITIVE_NON_EXPORT_COLUMNS:
                continue
            if field.export:
                unsafe_exports.append(f"{entry.table_name}.{field.name}")
            if field.erasure_action not in _SENSITIVE_NON_EXPORT_ACTIONS:
                unsafe_actions.append(f"{entry.table_name}.{field.name}")

            allowed_classifications = _SENSITIVE_COLUMN_ALLOWED_CLASSIFICATIONS[
                field.name
            ]
            if field.classification not in allowed_classifications:
                unsafe_classifications.append(f"{entry.table_name}.{field.name}")

    assert unsafe_exports == []
    assert unsafe_actions == []
    assert unsafe_classifications == []
