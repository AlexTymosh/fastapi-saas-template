# Privacy provider registry alignment

## Purpose

The privacy provider catalogue has three runtime surfaces that must stay aligned:

- `PRIVACY_DATA_INVENTORY` in `app.privacy.data_inventory`;
- the central provider-key catalogue in `app.privacy.provider_keys`;
- runtime export providers, erasure coverage and erasure orchestration order.

The central provider-key module is the stable key and table mapping catalogue.
Inventory rows declare which provider keys belong to each table. Runtime export
providers and erasure coverage must use the same keys and table mapping.

The erasure-order contract calls the runtime `_run_core_providers()` path with
patched providers and asserts the emitted provider result order. It does not
trust wrapper functions that only return the central catalogue order.

## Regression contract

`tests/privacy/test_privacy_provider_registry_alignment.py` verifies that:

- inventory export provider keys match `export_provider_keys()`;
- inventory erasure provider keys match `erasure_provider_keys()`;
- inventory table names match the central export/erasure table mapping;
- runtime export provider order matches `export_provider_order()`;
- runtime export provider table names match the central table mapping;
- `build_privacy_provider_registry()` contains only central catalogue keys;
- erasure coverage matches the central erasure provider catalogue;
- the actual `_run_core_providers()` emitted provider result order matches the
  central erasure provider order.

## Change rule

When adding, removing or renaming a DSR provider, update the central catalogue,
the inventory row and the runtime provider together in the same PR. The provider
registry alignment contract should fail if one surface changes without the
others.

Do not add ad-hoc provider keys directly in runtime providers, coverage maps or
docs without adding them to the central catalogue and privacy inventory.
