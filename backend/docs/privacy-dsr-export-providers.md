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

# DSR subject export providers

## Historical context

This slice replaced the metadata-only DSR export payload with a provider-based
JSON export for the current DSR inventory tables.

## Provider coverage introduced by this slice

Implemented provider coverage:

- `users.profile`
- `memberships.by_subject`
- `organisations.by_subject_membership`
- `invites.by_subject_email_or_revoker`
- `outbox.subject_references`
- `audit.subject_actor_or_target_join_events`
- `platform_staff.by_subject_or_creator`
- `dsr.workflow_records`
- `export_artifacts.subject_or_actor_metadata`
- `privacy_governance.authorizations`
- `privacy_governance.consent_records`
- `privacy_governance.notice_acceptances`

The exporter kept the previous top-level schema keys for compatibility and
added:

- `manifest`
- `manifest.providers`
- `manifest.record_count`
- `manifest.redaction_notices`
- `data`

## Redaction rules

The export intentionally does not include:

- invite `token_hash`
- outbox raw `payload_json`
- outbox `encrypted_raw_token`
- export artifact `storage_key`
- export artifact `processing_token`
- DSR idempotency hashes or fingerprints
- free-text audit `reason`
- non-allowlisted audit `metadata_json` keys
- internal failure details

Outbox rows are exported as references only. This preserves useful delivery
context without exposing invite email values or encrypted token material.

Audit rows are exported with allowlisted structured metadata only. Free-text
reason fields are reported through redaction notices rather than copied into the
subject export.

## Provider iteration model

Subject export providers must not materialise an unbounded provider result set
with `.all()`. Multi-row providers use deterministic keyset pagination over the
provider ordering column and `id` tie-breaker, with a bounded batch size. This
keeps export generation memory-bounded while preserving stable output order.

Provider queries that need related IDs should prefer SQL subqueries over loading
large ID lists into Python before the main export query. Email-based helper
subqueries must preserve the same trim/lower normalisation used by direct
provider lookups.

The non-streaming `CrossTableSubjectDataExporter.export_subject_data()` still
returns the existing in-memory export payload for compatibility. The provider
layer beneath it is now batched so the same providers can feed streaming archive
generation without eager provider-level result materialisation.

## PostgreSQL provider integration coverage

SQLite-backed tests cover the default fast feedback loop. PostgreSQL-specific
coverage is also required for provider queries that depend on JSON column
predicates, because PostgreSQL renders JSON element access through dialect
operators rather than SQLite's JSON helpers.

Current PostgreSQL provider coverage exercises:

- subject export lookup through `outbox_events.payload_json["email"]`;
- erasure impact counts through the same outbox JSON email predicate;
- erasure outbox scrubbing through the PostgreSQL JSON predicate plus
  `SELECT ... FOR UPDATE` locking path.

These tests are marked `privacy`, `integration` and `container`. They use the
existing Testcontainers PostgreSQL fixture and must remain outside the
`external_db` marker because they start their own disposable PostgreSQL instance.

## Contract guardrails

The subject export implementation must stay aligned with the privacy inventory.

Required checks:

- every inventory `export_provider_key` has exactly one concrete subject export
  provider;
- every concrete subject export provider points to the same table as the
  matching inventory entry;
- provider keys are unique;
- concrete providers expose the async `iter_export_records()` contract;
- multi-row providers do not use unbounded eager `.all()` result loading;
- provider keyset pagination keeps deterministic ordering across batch
  boundaries.

A dedicated contract test enforces these rules so future personal-data models
cannot silently enter the inventory without export-provider coverage.

## Superseded follow-up status

The original follow-up list has been completed or moved into non-blocking
follow-up categories.

Current implemented scope includes:

- provider-backed subject exports;
- batched/keyset provider iteration for multi-row subject export providers;
- PostgreSQL provider integration coverage for outbox JSON predicates;
- S3-compatible export object storage;
- erasure/anonymisation providers;
- retention purge for expired export objects.

Non-blocking follow-up categories include:

- streaming archive generation for very large exports;
- a versioned export payload schema contract.
