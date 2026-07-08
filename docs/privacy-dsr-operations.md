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

## Covered jobs

| Area | Signals |
|---|---|
| DSR requests | Current counts by request type and execution status. |
| DSR requests | Failed and stale queued/processing counts. |
| Export artifacts | Current counts by artifact status. |
| Export artifacts | Failed artifacts and stale queued/processing artifacts. |

Only `export` and `erase` DSR request types are included because those are the
request types that currently have execution workflows.

Aggregate database reads live in a dedicated privacy read-model repository so
the service layer only orchestrates the health snapshot and observability side
effects.

## Health status

The snapshot status is `ok` when there are no failed or stale execution jobs.
The status is `degraded` when any of these conditions are present:

- failed or partially fulfilled DSR execution requests
- stale queued or processing DSR execution requests
- failed export artifacts
- stale queued export artifacts
- processing export artifacts with an expired or missing stale lease

Processing export DSR requests are not counted as stale while they have a
processing export artifact with an active future lease. This avoids false alarms
for large exports where the worker heartbeat is still renewing the artifact
lease.

## Metrics

The snapshot updates OpenTelemetry instruments using the existing project
observability layer:

- `privacy.dsr.health_checks.total`
- `privacy.dsr.jobs`

The CLI initializes the configured observability provider before collecting the
snapshot and shuts it down afterwards, which also runs the provider flush path.
With metrics disabled or `OBSERVABILITY__EXPORTER=none`, this remains a no-op.

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
uv run pytest tests/observability/test_metrics.py
```
