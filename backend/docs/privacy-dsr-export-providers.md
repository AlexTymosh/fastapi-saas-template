# DSR subject export providers

## Scope

This slice replaces the metadata-only DSR export payload with a provider-based
JSON export for the current DSR inventory tables.

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

The exporter keeps the previous top-level schema keys for compatibility and
adds:

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

## Contract guardrails

The subject export implementation must stay aligned with the privacy inventory.

Required checks:

- every inventory `export_provider_key` has exactly one concrete subject export
  provider;
- every concrete subject export provider points to the same table as the
  matching inventory entry;
- provider keys are unique;
- concrete providers expose the async `iter_export_records()` contract.

A dedicated contract test should enforce these rules so future personal-data
models cannot silently enter the inventory without export-provider coverage.

## Remaining work

This is not the final 328-3 implementation.

Remaining follow-up work:

- split large exports into multiple ZIP entries instead of one in-memory
  `export.json`;
- add a streaming archive writer;
- add production object storage;
- add erasure/anonymisation providers;
- add retention purge for expired export objects;
- add larger integration tests on PostgreSQL-compatible JSON predicates;
- add a versioned export payload schema contract.
