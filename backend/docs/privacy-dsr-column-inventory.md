# DSR Column Inventory Contract

## Purpose

This document describes the follow-up contract added after the first DSR data
inventory slice.

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

## Why this should be merged before full export providers

The next major phase is cross-table export provider implementation. Without
column-level coverage, that phase can accidentally export too little, export too
much, or miss new columns added during parallel development.

This slice is low-risk because it adds a contract and tests only. It does not add
migrations, API changes, runtime behaviour changes, or storage behaviour changes.

## Suggested validation

```bash
cd backend
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pytest -q tests/privacy/test_privacy_column_inventory_contract.py
uv run --frozen pytest -q tests/privacy/test_privacy_data_inventory_contract.py
uv run --frozen pytest -q -m "privacy and not external_db"
task ci
```
