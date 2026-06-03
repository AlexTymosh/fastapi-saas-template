from __future__ import annotations

import inspect
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


def _subject_export_provider_entries() -> dict[str, type[Any]]:
    return {
        provider_type.provider_key: provider_type
        for provider_type in _subject_export_provider_types()
    }


def test_subject_export_provider_keys_match_inventory_export_keys() -> None:
    inventory_entries = _inventory_export_entries()
    provider_entries = _subject_export_provider_entries()

    assert set(provider_entries) == set(inventory_entries)


def test_subject_export_provider_keys_are_unique() -> None:
    provider_keys = [
        provider_type.provider_key for provider_type in _subject_export_provider_types()
    ]

    assert len(provider_keys) == len(set(provider_keys))


def test_subject_export_provider_table_names_match_inventory() -> None:
    inventory_entries = _inventory_export_entries()

    for provider_key, provider_type in _subject_export_provider_entries().items():
        assert provider_type.table_name == inventory_entries[provider_key].table_name


def test_subject_export_providers_expose_async_generator_iterators() -> None:
    for provider_type in _subject_export_provider_types():
        iterator = provider_type.iter_export_records

        assert inspect.isasyncgenfunction(iterator), provider_type.provider_key
