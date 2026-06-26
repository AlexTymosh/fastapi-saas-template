# DSR Column Inventory Contract

## Purpose

This document describes the column-level privacy inventory contract.

The table-level inventory is useful, but it is not enough on its own. A table can
be inventoried while a newly added column silently falls outside export,
erasure, anonymisation, retention, and documentation decisions.

The column inventory makes that failure mode visible in tests.

## Implemented files

- `app/privacy/column_inventory.py`
- `tests/privacy/test_privacy_column_inventory_contract.py`

## Contract

Every SQLAlchemy column on every DSR-inventoried table must have an explicit
`PrivacyColumnPolicy`.

A policy must state:

- table name;
- column name;
- privacy classification;
- whether the column is exported;
- erasure/anonymisation action;
- rationale.

This is intentionally stricter than the table-level inventory. The table-level
inventory describes DSR-scope fields that providers must understand. The column
inventory prevents accidental unclassified columns.

## Regression protection

The test suite fails when:

- a new column is added to an inventoried table without a matching policy;
- a policy references a column that no longer exists;
- a table-level inventory field disagrees with the matching column policy;
- a secret/token-classified column is exportable;
- internal storage keys, worker tokens, outbox payloads, or idempotency hashes are
  exposed through the export contract.

## Current status

The column inventory remains a current DSR/privacy contract. It must stay aligned
with the table-level inventory, export providers, erasure providers, and closure
checklist.

## Suggested validation

```bash
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pytest -q tests/privacy/test_privacy_column_inventory_contract.py
uv run --frozen pytest -q tests/privacy/test_privacy_data_inventory_contract.py
uv run --frozen pytest -q -m "privacy and not external_db"
task ci
```
