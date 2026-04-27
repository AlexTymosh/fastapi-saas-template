# Observability

## Current phase

- OpenTelemetry API instrumentation exists.
- Optional OpenTelemetry Metrics SDK lifecycle exists.
- Optional OTLP HTTP exporter configuration exists.
- No OTel Collector profile exists yet.
- No `/metrics` endpoint is exposed.
- Prometheus and Grafana are not connected yet.

## Current metrics foundation

The current foundation prepares rate-limit and HTTP metrics through OpenTelemetry API
instruments. Without an initialized SDK, these instruments behave as no-op implementations
at runtime. This keeps instrumentation points stable while preserving current runtime behavior.

## OpenTelemetry SDK and exporter

The project can initialize OpenTelemetry Metrics SDK when explicitly enabled.

Default behavior:

- `OBSERVABILITY__METRICS_ENABLED=false`
- `OBSERVABILITY__EXPORTER=none`
- no SDK/exporter is initialized
- OpenTelemetry API instruments remain no-op

OTLP HTTP exporter:

- set `OBSERVABILITY__METRICS_ENABLED=true`
- set `OBSERVABILITY__EXPORTER=otlp`
- set `OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics`

Tuning:

- `OBSERVABILITY__OTLP_TIMEOUT_SECONDS=2.0`
- `OBSERVABILITY__EXPORT_INTERVAL_MILLIS=60000`
- `OBSERVABILITY__EXPORT_TIMEOUT_MILLIS=2000`

Current limitations:

- no `/metrics` endpoint
- no Prometheus service
- no Grafana service
- no tracing
- no logs exporter
- no database/Redis auto-instrumentation

Implementation notes:

- `http.server.request.duration` is configured with explicit histogram buckets during SDK initialization.
- OpenTelemetry global `MeterProvider` is process-wide and set-once.
- Tests should use monkeypatch/fakes for lifecycle assertions and must not reset private OpenTelemetry globals.

## HTTP RED metrics foundation

The project records HTTP RED-style metrics through OpenTelemetry API instruments.

Current HTTP metric names:

- `http.server.requests.total`
- `http.server.errors.total`
- `http.server.request.duration`

Route label rule:

- use only route templates from `request.scope.get("route").path`;
- never use raw URL path;
- use `"unknown"` when route template is unavailable.

Error rule:

- 5xx responses are counted as errors;
- 4xx responses are not counted as server errors.

## Rate-limit observability outcomes

Rate-limit metrics use `rate_limit.result` to describe the limiter decision or failure mode.

| Result | Meaning | Expected HTTP behaviour | Operational meaning |
|---|---|---|---|
| `allowed` | Request passed the limiter | request continues | normal traffic |
| `blocked` | Request exceeded configured limit | 429 | client/user exceeded policy |
| `backend_error` | Limiter backend failed and policy failed closed | 503 | Redis/backend unavailable |
| `fail_open` | Limiter backend failed and policy allowed request | request continues | degraded protection mode |
| `runtime_unavailable` | Rate limiting is enabled but limiter runtime/limiter is missing | 503 | application lifecycle/configuration issue |

Current rate-limit metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Allowed `rate_limit.result` values:

- `allowed`
- `blocked`
- `backend_error`
- `fail_open`
- `runtime_unavailable`

Allowed labels/attributes:

- `rate_limit.policy`
- `rate_limit.result`
- `rate_limit.identifier_kind`
- `error.type`

Forbidden labels/attributes:

- user id
- email
- organisation id
- request id
- trace id
- raw path
- raw URL
- IP address
- token
- Redis key
- identifier value
- hashed identifier value

## Rate-limit dashboard signals

Recommended dashboard panels:

- allowed requests by policy;
- blocked requests by policy;
- backend errors by policy and error type;
- fail-open events by policy;
- runtime unavailable events;
- rate-limit check duration p50/p95/p99.

Recommended alert candidates:

- `runtime_unavailable > 0`: critical;
- `fail_open > 0` on sensitive policies: critical;
- sustained `backend_error > 0`: warning/critical depending on environment;
- sudden spike in `blocked`: warning/security investigation;
- high p95 `rate_limit.check.duration`: warning.

## Metrics recording failure handling

Metric recording is best-effort.

Failures in OpenTelemetry instruments, SDK/exporter integration, or observability helpers
must not affect API behavior.

The project records an internal self-metric:

- `observability.recording_failures.total`

Failure logs are rate-limited in-process to avoid log storms.

Failure logs must remain low-cardinality and must not include:

- user id
- email
- organisation id
- request id
- trace id
- raw path
- raw URL
- IP address
- token
- Redis key
- identifier value
- hashed identifier value
- exception message

## Future phases

- add optional OTel Collector profile for local verification;
- add Prometheus-compatible collection path;
- add Grafana dashboards;
- add alert rules.
