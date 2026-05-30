# Privacy DSR architecture contract

## Status

This document defines the first architecture-contract slice for issue #328.
It does not implement the final export or erasure execution pipeline. It makes
that pipeline safer to build by creating a mandatory inventory and provider
contract before more code is added.

## Problem

The project now has a DSR model, DSR API, export-artifact model, local storage
adapter and worker foundation. The remaining risk is that export and erasure
logic can become a set of ad-hoc SQL queries spread across services.

That would create three problems:

1. A new table can start storing personal data without being included in DSR
   export/erasure coverage.
2. Audit and compliance records can be deleted too aggressively, breaking
   integrity and legal evidence.
3. Outbox/invite/audit payloads can leak personal data into exports or be kept
   longer than necessary.

## Decision

Add a code-level privacy data inventory and provider registry contract:

- `app/privacy/data_inventory.py`
  - declares all current tables that are inside DSR scope;
  - declares explicit exclusions for non-subject tables;
  - identifies subject lookup strategy, data categories, fields, export provider
    key, erasure provider key, erasure strategy and retention policy key.
- `app/privacy/providers/base.py`
  - defines future export and erasure provider protocols.
- `app/privacy/providers/registry.py`
  - derives provider registry metadata from the inventory.
- `tests/privacy/test_privacy_data_inventory_contract.py`
  - fails if a SQLAlchemy model table is not either inventoried or explicitly
    excluded;
  - fails if core #328 tables are missing export/erasure coverage;
  - validates model references and provider-key consistency.

## Current inventory scope

The inventory covers the following current tables:

- `users`
- `memberships`
- `organisations`
- `invites`
- `outbox_events`
- `audit_events`
- `platform_staff`
- `data_subject_requests`
- `export_artifacts`
- `data_processing_authorizations`
- `consent_records`
- `privacy_notice_acceptances`

The inventory explicitly excludes:

- `processing_purposes` — static processing-purpose catalogue without a subject
  identifier column.

## Provider contract rules

Every DSR-scoped table must have:

1. A subject locator.
2. At least one field entry.
3. An export provider key.
4. An erasure strategy.
5. A retention policy key.
6. Either an erasure provider key or an explicit retain/minimise legal strategy.

Provider keys are intentionally string keys at this stage. They are stable names
that future implementation providers will bind to. This avoids importing future
runtime services into a static contract module.

## Why this is not over-engineering

The current issue is architectural, not just endpoint-level. DSR export and
anonymisation will cross users, memberships, organisations, invites, outbox,
audit, privacy-governance records and future patient/clinical records. A static
inventory with tests is cheaper than discovering missed personal data after a
feature has already shipped.

## What this does not do yet

This slice does not:

- generate full export files;
- query data through provider implementations;
- anonymise database records;
- delete export objects from storage;
- add migrations;
- change public API contracts;
- change permissions.

Those belong to later #328 child issues.

## Follow-up implementation order

1. Convert `MinimalSubjectDataExporter` to use inventory-backed export providers.
2. Add provider implementations for users, memberships, organisations, invites,
   outbox references and audit events.
3. Add execution-state separation so `fulfilled` cannot be set before export or
   erasure execution is complete.
4. Add erasure/anonymisation providers using the same inventory keys.
5. Add retention runners for export artifacts, outbox payloads, invite records
   and audit minimisation.
