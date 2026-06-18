from __future__ import annotations

import pytest

from app.privacy.data_inventory import PRIVACY_DATA_INVENTORY
from app.privacy.exporters import subject_data
from app.privacy.provider_keys import (
    export_provider_keys,
    export_provider_table_name,
)

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


def test_export_provider_keys_match_central_provider_keys() -> None:
    provider_keys = {
        provider_type.provider_key
        for provider_type in subject_data._EXPORT_PROVIDER_TYPES
    }

    assert provider_keys == set(export_provider_keys())


def test_export_provider_tables_match_central_provider_keys() -> None:
    for provider_type in subject_data._EXPORT_PROVIDER_TYPES:
        assert provider_type.table_name == export_provider_table_name(
            provider_type.provider_key
        )


def test_inventory_export_keys_match_central_provider_keys() -> None:
    inventory_keys = {entry.export_provider_key for entry in PRIVACY_DATA_INVENTORY}

    assert inventory_keys == set(export_provider_keys())
