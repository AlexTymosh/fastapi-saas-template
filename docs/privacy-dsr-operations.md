# Privacy DSR operations visibility

This document describes the operator-facing health, metrics and logging added for
DSR execution jobs after PR-328-10A.

## Command

From the repository root:

```bash
task privacy:dsr-health
```

From `backend` directly:

```bash
uv run --locked python -m app.commands.privacy_dsr_health
```

Use `--stale-after-seconds` to change the queued/processing staleness threshold
for one run. The default is 3600 seconds.

On Windows, the command uses a selector-based event loop for PostgreSQL async
connections because Psycopg async connections are not compatible with the
default Proactor event loop.

The CLI owns an explicit database transaction around the read-only health
snapshot. The transaction commits after a successful snapshot and rolls back if
snapshot collection raises.

## Covered jobs

| Area | Signals |
|---|---|
| DSR requests | Current counts by request type and execution status. |
| DSR requests | Failed and stale queued/processing counts. |
| Export artifacts | Current counts by artifact status. |
| Export artifacts | Current failed artifacts. |
| Export artifacts | Stale queued/processing artifacts and expired ready artifacts. |

Only `export` and `erase` DSR request types are included because those are the
request types that currently have execution workflows.

Cancelled DSR requests are excluded from current, failed and stale DSR work
signals because cancellation intentionally removes the work from execution.

Aggregate database reads live in a dedicated privacy read-model repository so
the service layer only orchestrates the health snapshot and observability side
effects.

## Health status

The snapshot status is `ok` when there are no failed or stale execution jobs.
The status is `degraded` when any of these conditions are present:

- failed or partially fulfilled DSR execution requests
- stale queued or processing DSR execution requests
- current failed export artifacts that have not been superseded by a newer
  artifact for the same DSR
- stale queued export artifacts
- stale processing export artifacts with an expired or missing stale lease
- current ready export artifacts with `expires_at` in the past

Cancelled DSR requests, and export artifacts linked only to cancelled DSR
requests, are excluded from degraded failed/stale signals. Artifact by-status
counts can still include historical artifacts for cancelled requests.

Processing export DSR requests are not counted as stale while they have a
processing export artifact with an active future lease. This avoids false alarms
for large exports where the worker heartbeat is still renewing the artifact
lease.

Historical failed export artifacts remain visible in the by-status artifact
counts, but they do not degrade the snapshot once a newer artifact for the same
DSR becomes the current execution artifact.

Expired ready artifacts degrade the snapshot only when they are still the current
artifact for the DSR. If a newer artifact supersedes the expired row, the expired
row remains visible in by-status counts but no longer affects health.

## Metrics

The snapshot updates OpenTelemetry instruments using the existing project
observability layer:

- `privacy.dsr.health_checks.total`
- `privacy.dsr.jobs`

The CLI initializes the configured observability provider before collecting the
snapshot and shuts it down afterwards, which also runs the provider flush path.
With metrics disabled or `OBSERVABILITY__EXPORTER=none`, this remains a no-op.

The observable gauge reads a snapshot of the latest DSR job points under a lock.
Health snapshot recording builds a complete replacement map before swapping it
in, so periodic metric collection cannot observe a clear-then-update gap.

Failed-signal DSR metric points preserve the underlying execution status. A
`failed` job and a `partially_fulfilled` job are emitted as separate failed
signals instead of being relabelled into one `failed` execution status.

Stale export artifact metric points preserve the underlying artifact status.
Queued backlog, processing lease failures and expired ready artifacts are emitted
as separate stale signals instead of being collapsed under `processing`.

Metric attributes are intentionally low-cardinality and do not include request
IDs, user IDs, email addresses, storage keys, tokens, notes or free-form error
messages.

## Logging

Every snapshot emits one structured log event:

```text
privacy_dsr_execution_health_checked
```

The log contains only aggregate counts and the health status. It does not contain
personal data or per-request identifiers.

## Verification

Run the focused regression suite after changing this area:

```bash
uv run pytest tests/privacy/test_privacy_dsr_execution_health.py
uv run pytest tests/privacy/test_privacy_dsr_execution_health_cancelled.py
uv run pytest tests/privacy/test_privacy_dsr_execution_health_expired_artifacts.py
uv run pytest tests/observability/test_metrics.py
```
