from __future__ import annotations

from typing import Any

import pytest

from app.privacy.data_inventory import get_privacy_inventory_by_table
from app.privacy.exporters import subject_data

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


def _inventory_export_entries() -> dict[str, Any]:
    return {
        entry.export_provider_key: entry
        for entry in get_privacy_inventory_by_table().values()
    }


def _subject_export_provider_types() -> tuple[type[Any], ...]:
    provider_types = subject_data._EXPORT_PROVIDER_TYPES
    assert isinstance(provider_types, tuple)
    return provider_types


def test_subject_export_provider_keys_match_inventory_export_keys() -> None:
    inventory_entries = _inventory_export_entries()
    provider_types = _subject_export_provider_types()

    concrete_provider_keys = {
        provider_type.provider_key for provider_type in provider_types
    }

    assert concrete_provider_keys == set(inventory_entries)


def test_subject_export_provider_table_names_match_inventory_entries() -> None:
    inventory_entries = _inventory_export_entries()

    for provider_type in _subject_export_provider_types():
        provider_key = provider_type.provider_key
        inventory_entry = inventory_entries[provider_key]

        assert provider_type.table_name == inventory_entry.table_name


def test_subject_export_provider_keys_are_unique() -> None:
    provider_keys = [
        provider_type.provider_key for provider_type in _subject_export_provider_types()
    ]

    assert len(provider_keys) == len(set(provider_keys))


def test_subject_export_providers_expose_async_export_iterator_contract() -> None:
    for provider_type in _subject_export_provider_types():
        method = getattr(provider_type, "iter_export_records", None)

        assert callable(method), provider_type.provider_key
