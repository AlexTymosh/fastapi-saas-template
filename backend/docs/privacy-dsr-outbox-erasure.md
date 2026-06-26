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

# DSR outbox erasure provider

## Historical context

This document described the controlled mutation provider for:

- `outbox.purge_or_scrub_payload`

The provider has since been included in the current erasure orchestration flow.

## Current status

Outbox payload scrubbing is part of the inventory-aligned erasure workflow
described in `backend/docs/privacy-dsr.md`.

## Purpose

Outbox rows may contain delivery-only personal data and secrets in
`payload_json`, such as invite email addresses or encrypted raw invite tokens.

After an erasure request is approved, subject-linked outbox payloads must be
scrubbed before the workflow can be considered complete.

## Matching rules

The provider can match subject-linked rows by:

- invite id snapshots via `aggregate_id`;
- subject email snapshots via `payload_json.email`.

Snapshot parameters are required because earlier providers may remove the
current database values that would otherwise be used for matching.

## Mutation rules

For matched rows, the provider:

- preserves safe operational references;
- removes delivery-only or unsafe payload values;
- adds scrub markers to `payload_json`;
- terminalises pending rows with a safe reason code where allowed;
- blocks unsafe in-flight processing rows;
- clears unsafe historical `last_error` values on already-terminal rows.
