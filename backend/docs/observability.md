# Observability

## Current phase

- The project currently uses `opentelemetry-api` only.
- No OpenTelemetry SDK is initialized yet.
- No exporter is configured yet.
- No `/metrics` endpoint is exposed.
- Prometheus and Grafana are not connected at this phase.

## Current metrics foundation

The current foundation prepares rate-limit metrics through OpenTelemetry API instruments.
Without an initialized SDK, these instruments behave as no-op implementations at runtime.
This allows stable instrumentation points now, while keeping runtime behavior unchanged.

Current rate-limit metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

## Rate-limit metric results

Allowed result values:

- `allowed`
- `blocked`
- `backend_error`
- `fail_open`

## Low-cardinality rules

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

## Route template rule

Future HTTP metrics must use route templates only:

`request.scope.get("route").path`

Do not use:

- `request.url.path`
- raw path
- raw URL

If the route template is unavailable, use `"unknown"`.

## Future phases

Next phase:

- initialize OpenTelemetry SDK
- add exporter
- expose or export metrics for Prometheus-compatible collection
- prepare Grafana dashboard

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

Meter provider lifecycle note:

- OpenTelemetry global `MeterProvider` is process-wide and set once;
- tests must use monkeypatch/fakes for `metrics.set_meter_provider`;
- tests must not reset private OpenTelemetry globals.

## HTTP RED metrics foundation

The project records HTTP RED-style metrics through OpenTelemetry API instruments.

Current HTTP metric names:

- `http.server.requests.total`
- `http.server.errors.total`
- `http.server.request.duration`

HTTP request duration aggregation:

- `http.server.request.duration` uses explicit histogram bucket boundaries;
- boundaries are configured in SDK initialization for predictable latency slices.

Current phase:

- no OpenTelemetry SDK is initialized;
- no exporter is configured;
- no `/metrics` endpoint is exposed;
- Prometheus and Grafana are not connected yet.

Route label rule:

- use only route templates from `request.scope.get("route").path`;
- never use raw URL path;
- use `"unknown"` when route template is unavailable.

Error rule:

- 5xx responses are counted as errors;
- 4xx responses are not counted as server errors.

## Metrics recording failure handling

Metric recording is best-effort.

Failures in OpenTelemetry instruments, future SDK/exporter integration, or observability
helpers must not affect API behavior.

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
