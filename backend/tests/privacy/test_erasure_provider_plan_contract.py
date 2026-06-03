from __future__ import annotations

import pytest

from app.privacy.data_inventory import (
    PRIVACY_DATA_INVENTORY,
    PrivacyErasureStrategy,
    PrivacyFieldErasureAction,
)
from app.privacy.erasures.plan import (
    ErasureExecutionMode,
    build_erasure_provider_plan,
    get_erasure_provider_plan_by_key,
)

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


def test_erasure_provider_plan_covers_inventory_erasure_keys() -> None:
    expected_keys = {
        entry.erasure_provider_key
        for entry in PRIVACY_DATA_INVENTORY
        if entry.erasure_provider_key is not None
    }
    actual_keys = set(get_erasure_provider_plan_by_key())

    assert actual_keys == expected_keys


def test_erasure_provider_plan_has_unique_provider_keys() -> None:
    entries = build_erasure_provider_plan()
    provider_keys = [entry.provider_key for entry in entries]

    assert len(provider_keys) == len(set(provider_keys))


def test_erasure_provider_plan_matches_inventory_metadata() -> None:
    by_key = get_erasure_provider_plan_by_key()

    for inventory_entry in PRIVACY_DATA_INVENTORY:
        provider_key = inventory_entry.erasure_provider_key
        if provider_key is None:
            continue

        plan_entry = by_key[provider_key]

        assert plan_entry.table_name == inventory_entry.table_name
        assert plan_entry.strategy == inventory_entry.erasure_strategy
        assert plan_entry.retention_policy_key == (inventory_entry.retention_policy_key)


@pytest.mark.parametrize(
    ("strategy", "expected_mode"),
    [
        (PrivacyErasureStrategy.ANONYMISE_SUBJECT, ErasureExecutionMode.ANONYMISE),
        (
            PrivacyErasureStrategy.DELETE_WHEN_ALLOWED,
            ErasureExecutionMode.DELETE_WHEN_ALLOWED,
        ),
        (
            PrivacyErasureStrategy.RETAIN_AND_MINIMISE,
            ErasureExecutionMode.RETAIN_AND_MINIMISE,
        ),
        (
            PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
            ErasureExecutionMode.RETAIN_WITH_LEGAL_BASIS,
        ),
        (PrivacyErasureStrategy.NOT_APPLICABLE, ErasureExecutionMode.NOT_APPLICABLE),
    ],
)
def test_erasure_provider_plan_maps_strategy_to_execution_mode(
    strategy: PrivacyErasureStrategy,
    expected_mode: ErasureExecutionMode,
) -> None:
    modes = {
        entry.execution_mode
        for entry in build_erasure_provider_plan()
        if entry.strategy is strategy
    }

    assert modes <= {expected_mode}


def test_review_required_fields_are_marked_for_manual_review() -> None:
    by_key = get_erasure_provider_plan_by_key()

    for inventory_entry in PRIVACY_DATA_INVENTORY:
        provider_key = inventory_entry.erasure_provider_key
        if provider_key is None:
            continue

        has_review_field = any(
            field.erasure_action is PrivacyFieldErasureAction.REVIEW_REQUIRED
            for field in inventory_entry.fields
        )
        if has_review_field:
            assert by_key[provider_key].requires_manual_review is True
