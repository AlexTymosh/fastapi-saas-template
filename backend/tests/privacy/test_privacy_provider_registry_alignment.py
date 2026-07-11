from __future__ import annotations

import pytest

from app.privacy.data_inventory import PRIVACY_DATA_INVENTORY
from app.privacy.erasures.coverage import ERASURE_COVERAGE_MAP
from app.privacy.erasures.orchestrator import (
    erasure_orchestration_provider_order as runtime_erasure_provider_order,
)
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

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


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


def test_erasure_coverage_and_runtime_order_match_central_catalogues() -> None:
    assert set(ERASURE_COVERAGE_MAP) == erasure_provider_keys()
    assert runtime_erasure_provider_order() == erasure_orchestration_provider_order()
    assert set(runtime_erasure_provider_order()) == erasure_provider_keys()
