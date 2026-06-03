from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.privacy.data_inventory import (
    PRIVACY_DATA_INVENTORY,
    PrivacyErasureStrategy,
    PrivacyFieldErasureAction,
)


class ErasureExecutionMode(StrEnum):
    ANONYMISE = "anonymise"
    DELETE_WHEN_ALLOWED = "delete_when_allowed"
    RETAIN_AND_MINIMISE = "retain_and_minimise"
    RETAIN_WITH_LEGAL_BASIS = "retain_with_legal_basis"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ErasureProviderPlanEntry:
    provider_key: str
    table_name: str
    strategy: PrivacyErasureStrategy
    execution_mode: ErasureExecutionMode
    retention_policy_key: str
    requires_manual_review: bool


def build_erasure_provider_plan() -> tuple[ErasureProviderPlanEntry, ...]:
    """Build the erasure-provider implementation plan from the inventory.

    This is intentionally not an execution engine. It gives the next #328
    branch a single source of truth for which erasure providers must exist and
    which rows require manual/legal review before mutation.
    """

    entries: list[ErasureProviderPlanEntry] = []
    seen_provider_keys: set[str] = set()

    for inventory_entry in PRIVACY_DATA_INVENTORY:
        provider_key = inventory_entry.erasure_provider_key
        if provider_key is None:
            continue
        if provider_key in seen_provider_keys:
            raise ValueError(f"Duplicate erasure provider key: {provider_key}")

        seen_provider_keys.add(provider_key)
        entries.append(
            ErasureProviderPlanEntry(
                provider_key=provider_key,
                table_name=inventory_entry.table_name,
                strategy=inventory_entry.erasure_strategy,
                execution_mode=_execution_mode_for_strategy(
                    inventory_entry.erasure_strategy
                ),
                retention_policy_key=inventory_entry.retention_policy_key,
                requires_manual_review=_requires_manual_review(inventory_entry),
            )
        )

    return tuple(entries)


def get_erasure_provider_plan_by_key() -> dict[str, ErasureProviderPlanEntry]:
    return {entry.provider_key: entry for entry in build_erasure_provider_plan()}


def _execution_mode_for_strategy(
    strategy: PrivacyErasureStrategy,
) -> ErasureExecutionMode:
    if strategy is PrivacyErasureStrategy.ANONYMISE_SUBJECT:
        return ErasureExecutionMode.ANONYMISE
    if strategy is PrivacyErasureStrategy.DELETE_WHEN_ALLOWED:
        return ErasureExecutionMode.DELETE_WHEN_ALLOWED
    if strategy is PrivacyErasureStrategy.RETAIN_AND_MINIMISE:
        return ErasureExecutionMode.RETAIN_AND_MINIMISE
    if strategy is PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS:
        return ErasureExecutionMode.RETAIN_WITH_LEGAL_BASIS
    if strategy is PrivacyErasureStrategy.NOT_APPLICABLE:
        return ErasureExecutionMode.NOT_APPLICABLE
    raise ValueError(f"Unsupported erasure strategy: {strategy}")


def _requires_manual_review(inventory_entry: object) -> bool:
    fields = inventory_entry.fields
    if any(
        field.erasure_action is PrivacyFieldErasureAction.REVIEW_REQUIRED
        for field in fields
    ):
        return True

    return inventory_entry.erasure_strategy in {
        PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
        PrivacyErasureStrategy.NOT_APPLICABLE,
    }
