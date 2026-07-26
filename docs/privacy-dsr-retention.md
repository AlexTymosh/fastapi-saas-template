# Privacy DSR retention maintenance

This document describes the bounded retention pass used for issue #328 DSR data.
The retention command now covers more than export artifacts.

## Command

From the repository root:

```bash
task privacy:retention:dry-run
task privacy:retention:once
```

From `backend` directly:

```bash
uv run --locked python -m app.privacy.retention_cli --dry-run
uv run --locked python -m app.privacy.retention_cli
```

Use `--batch-size` to cap each retention step in one run. The same limit is
applied independently to export artifacts, invites, outbox events, audit events
and DSR idempotency rows.

## Covered data

| Area | Retention action |
|---|---|
| Export artifacts | Prioritise erasure and failed-upload retries, then expire READY rows. |
| Invites | Replace retained invite email/token values with deterministic tombstones. |
| Outbox events | Scrub delivered/failed delivery payloads after the retention window. |
| Audit events | Remove old actor, free-form, network and user-agent context. |
| DSR idempotency | Clear expired hashes, fingerprints and expiry timestamps. |

## Safety boundaries

- The maintenance helper does not commit. The caller owns transaction control.
- Dry-run mode performs a preview and must not mutate database rows or storage.
- Invite and outbox SQL queries filter out already retained rows before applying
  the batch limit. Repeated runs must not let older no-op rows starve later
  mutable rows.
- Pending and processing outbox events are excluded because a worker may still
  hold or deliver their payload.
- Audit rows with an active legal hold are excluded from retention minimisation.
- Audit minimisation rechecks age, legal-hold and mutable-field predicates in the
  bulk `UPDATE`, not only during the initial ID selection.
- Retention must not delete a stored export object while rollback could restore
  the artifact to `ready`.
- Erasure-cancelled purge retries keep first priority under small batches. If a
  retry purge succeeds and consumes the batch, unrelated READY rows wait for the
  next retention pass.
- Failed export generation/upload rows retain their committed `storage_key`
  until object deletion succeeds. They are non-downloadable and have second
  cleanup priority, before new READY expiry work. Missing objects are accepted
  as an idempotent cleanup success.
- Export publishers first create a storage reservation and publish only by
  replacing that exact revision. Cleanup conditionally removes the current
  reservation or object revision before clearing the database key. A publisher
  that resumes after committed cleanup therefore cannot recreate an untracked
  object. A successful publish consumes the reservation and does not run a
  separate cancellation request. An ambiguous conditional response is accepted
  only when storage metadata matches the committed checksum and size.
  Transport-level acknowledgement failures use the same `HeadObject`
  reconciliation. If object state cannot be inspected, the committed intent
  remains `processing` for stale recovery instead of entering failed cleanup.
- READY export artifacts transition to `expired` while keeping `storage_key` as
  a purge retry marker. This transition is independent of retry purge failures,
  so a temporary object-store outage must not keep unrelated expired READY
  exports downloadable. A later pass may delete the object and clear storage
  metadata only after the caller commits the expiry transition. Repeated passes
  inside the same caller-owned transaction must skip artifacts expired by that
  transaction. Expiry markers are cleared on commit or rollback, not by polling
  session state, because reads may autobegin a new transaction. Eligible expired
  retry rows must exclude those markers before applying the batch limit.
- Storage purge failures remain retryable. When a failure prevents all useful
  retention work in the pass, the original storage exception is surfaced so
  operators and tests still observe the outage.
- S3-compatible cleanup is key-level deletion. A versioning-enabled production
  bucket must permanently expire noncurrent versions and expired delete markers
  within the retention SLA, or use a dedicated unversioned bucket/prefix.
- S3-compatible providers must support conditional `PutObject` with
  `If-None-Match: *` and `If-Match`, conditional `DeleteObject` with `If-Match`,
  and read-after-write `HeadObject` metadata. Cleanup and publication fail
  closed when these preconditions are unavailable.
- Erasure-cancelled artifacts use the same retry-marker model: object deletion
  is retried only after the row is already `cancelled` for subject erasure.
- Export artifact object deletion remains delegated to `ExportArtifactService` so
  DB state and object storage cleanup stay consistent.

## Operator output

The CLI prints a per-step summary, for example:

```text
Privacy retention retained 4 total (expired_export_artifacts=0,
anonymised_invites=1, scrubbed_outbox_events=1, minimised_audit_events=1,
cleaned_dsr_idempotency_keys=1)
```

The command also emits a structured log summary without personal data, raw email,
invite token material, outbox payloads or storage keys.

## Verification

Run the focused regression suite after changing this area:

```bash
uv run pytest tests/privacy/test_privacy_retention_maintenance.py
uv run pytest tests/privacy/test_export_artifact_service.py
uv run pytest tests/privacy/test_privacy_data_inventory_contract.py
uv run pytest tests/contracts/test_privacy_docs_contract.py
```
