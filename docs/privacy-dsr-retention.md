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
| Export artifacts | Expire ready artifacts and purge stored archive objects. |
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
uv run pytest tests/privacy/test_privacy_data_inventory_contract.py
```
