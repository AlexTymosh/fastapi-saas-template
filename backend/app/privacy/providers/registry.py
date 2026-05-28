from __future__ import annotations

from dataclasses import dataclass

from app.privacy.data_inventory import (
    PRIVACY_DATA_INVENTORY,
    PrivacyErasureStrategy,
    get_privacy_inventory_by_table,
)


@dataclass(frozen=True, slots=True)
class PrivacyProviderRegistryEntry:
    provider_key: str
    table_name: str
    purpose: str
    erasure_strategy: PrivacyErasureStrategy
    retention_policy_key: str


def _add_provider_entry(
    registry: dict[str, PrivacyProviderRegistryEntry],
    *,
    provider_key: str,
    table_name: str,
    purpose: str,
    erasure_strategy: PrivacyErasureStrategy,
    retention_policy_key: str,
) -> None:
    existing = registry.get(provider_key)
    if existing is not None:
        raise ValueError(
            "Duplicate privacy provider key "
            f"{provider_key!r}: {existing.table_name}/{existing.purpose} and "
            f"{table_name}/{purpose}"
        )

    registry[provider_key] = PrivacyProviderRegistryEntry(
        provider_key=provider_key,
        table_name=table_name,
        purpose=purpose,
        erasure_strategy=erasure_strategy,
        retention_policy_key=retention_policy_key,
    )


def build_privacy_provider_registry() -> dict[str, PrivacyProviderRegistryEntry]:
    registry: dict[str, PrivacyProviderRegistryEntry] = {}
    for inventory_entry in PRIVACY_DATA_INVENTORY:
        _add_provider_entry(
            registry,
            provider_key=inventory_entry.export_provider_key,
            table_name=inventory_entry.table_name,
            purpose="export",
            erasure_strategy=inventory_entry.erasure_strategy,
            retention_policy_key=inventory_entry.retention_policy_key,
        )
        if inventory_entry.erasure_provider_key is not None:
            _add_provider_entry(
                registry,
                provider_key=inventory_entry.erasure_provider_key,
                table_name=inventory_entry.table_name,
                purpose="erasure",
                erasure_strategy=inventory_entry.erasure_strategy,
                retention_policy_key=inventory_entry.retention_policy_key,
            )
    return registry


def get_provider_entry(provider_key: str) -> PrivacyProviderRegistryEntry:
    return build_privacy_provider_registry()[provider_key]


def get_table_provider_entries(table_name: str) -> list[PrivacyProviderRegistryEntry]:
    inventory_entry = get_privacy_inventory_by_table()[table_name]
    registry = build_privacy_provider_registry()
    provider_keys = [inventory_entry.export_provider_key]
    if inventory_entry.erasure_provider_key is not None:
        provider_keys.append(inventory_entry.erasure_provider_key)
    return [registry[key] for key in provider_keys]
