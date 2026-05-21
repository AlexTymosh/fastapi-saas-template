# Audit retention and anonymisation

This document describes the operational policy for audit-event retention.

## Objective

Audit records should remain useful for accountability and incident investigation, but they must not keep directly identifying personal data for longer than necessary.

The retention job anonymises expired audit events instead of deleting rows. This keeps the security/audit timeline intact while removing fields that can identify a person.

## Data anonymised after expiry

The existing audit retention service clears these fields for expired rows:

- `actor_user_id`
- `reason`
- `metadata_json`
- `ip_address`
- `user_agent`

The job preserves non-identifying audit structure:

- `id`
- `category`
- `action`
- `target_type`
- `target_id`
- `created_at`
- `legal_hold_until`

Rows under active legal hold are not anonymised.

## Retention settings

Configure retention through the existing `AUDIT__*` settings:

| Setting | Purpose | Default |
| --- | --- | ---: |
| `AUDIT__RETENTION_DAYS` | Tenant/platform audit events | `365` |
| `AUDIT__SECURITY_RETENTION_DAYS` | Security audit events | `730` |
| `AUDIT__COMPLIANCE_RETENTION_DAYS` | Compliance audit events | `2555` |
| `AUDIT__ANONYMISATION_BATCH_SIZE` | Maximum rows processed per category per run | `1000` |
| `AUDIT__NETWORK_IDENTIFIER_SECRET` | HMAC secret for stable network identifiers before storage | unset |

`AUDIT__NETWORK_IDENTIFIER_SECRET` should be set in non-local environments and must be at least 32 characters long.

## Manual run

From the `backend` directory:

```bash
uv run python -m app.audit.retention_cli
```

Quiet mode, suitable for scheduler logs that already capture process status:

```bash
uv run python -m app.audit.retention_cli --quiet
```

Dry-run mode counts the rows that would be anonymised and rolls the transaction back:

```bash
uv run python -m app.audit.retention_cli --dry-run
```

Quiet dry-run mode:

```bash
uv run python -m app.audit.retention_cli --dry-run --quiet
```

## Scheduling guidance

Run this as an explicit maintenance job rather than during API startup.

Recommended options:

- production: daily scheduled job, Kubernetes CronJob, container scheduler, or platform-native scheduled task;
- staging: daily or on-demand before privacy/security test cycles;
- local development: manual execution only.

The normal job commits once per run. If anonymisation fails, the transaction is not committed and the process exits with a non-zero error.

In `--dry-run` mode, the command executes the same selection/anonymisation path to calculate the affected row count, then rolls the transaction back before exit.

## Verification

Targeted test command:

```bash
uv run pytest tests/audit/test_audit_event_service.py tests/audit/test_audit_retention_maintenance.py tests/audit/test_audit_retention_cli.py -q
```

Full backend gate:

```bash
task ci
```
