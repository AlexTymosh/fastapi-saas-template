> Historical implementation-slice note.
>
> This document describes an earlier implementation slice of issue #328.
> It is not the current DSR/privacy source of truth.
>
> Current status is documented in:
>
> - `backend/docs/privacy-dsr.md`
> - `backend/docs/privacy-dsr-328-closure-checklist.md`
> - `backend/docs/current-state.md`

# Privacy DSR architecture contract

## Historical context

This document defines the architecture-contract slice that introduced the
privacy inventory and provider registry idea for issue #328.

It is preserved because the architectural decision remains useful, but the
implementation status in the original slice has been superseded by the current
DSR/export/erasure implementation.

## Current source of truth

Use these documents for current implementation status:

- `backend/docs/privacy-dsr.md`;
- `backend/docs/privacy-dsr-328-closure-checklist.md`;
- `backend/docs/privacy-export-artifacts.md`;
- `backend/docs/current-state.md`.

## Original problem

DSR export and erasure logic can become unsafe if subject lookups and mutation
rules are spread across services as ad-hoc SQL.

That creates three risks:

1. A new table can store personal data without being included in DSR coverage.
2. Audit and compliance records can be deleted too aggressively, breaking
   integrity and legal evidence.
3. Outbox, invite, audit, and privacy-governance payloads can leak personal data
   into exports or retain it longer than necessary.

## Decision

The project uses a code-level privacy data inventory and provider registry
contract.

The inventory declares:

- DSR-scoped tables;
- explicit exclusions for non-subject tables;
- subject lookup strategy;
- data categories;
- fields;
- export provider keys;
- erasure provider keys;
- erasure strategy;
- retention policy keys.

## Current inventory scope

The current inventory covers:

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

The inventory explicitly excludes static, non-subject catalogue tables where
there is no subject identifier column.

## Provider contract rules

Every DSR-scoped table must have:

1. a subject locator;
2. at least one field entry;
3. an export provider key;
4. an erasure strategy;
5. a retention policy key;
6. either an erasure provider key or an explicit retain/minimise legal strategy.

## Why this is not over-engineering

The DSR workflow crosses users, memberships, organisations, invites, outbox,
audit, export artifacts, DSR workflow records, platform staff records, and
privacy-governance records.

A static inventory with contract tests is cheaper and safer than discovering
missed personal-data stores after a feature has shipped.

## Superseded follow-up status

The original follow-up implementation order has been completed or superseded by
the current DSR implementation.

Current implemented scope includes:

- inventory-backed export providers;
- executable and policy-based erasure providers;
- execution-state separation;
- export artifact storage and retention;
- platform DSR and erasure APIs;
- provider decision preservation;
- privacy documentation contract tests.
