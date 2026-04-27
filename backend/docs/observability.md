# Observability

## Current phase

- OpenTelemetry API instrumentation exists in the application.
- OpenTelemetry Metrics SDK and OTLP exporter are available, but **disabled by default**.
- No `/metrics` endpoint is exposed.
- Prometheus and Grafana are **not** part of the current phase.

## Runtime switches

Default behavior:

- `OBSERVABILITY__METRICS_ENABLED=false`
- `OBSERVABILITY__EXPORTER=none`
- no SDK/exporter initialization
- metric recording remains safe and best-effort

To enable OTLP metrics export:

- `OBSERVABILITY__METRICS_ENABLED=true`
- `OBSERVABILITY__EXPORTER=otlp`
- `OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics`

Tuning:

- `OBSERVABILITY__OTLP_TIMEOUT_SECONDS=2.0`
- `OBSERVABILITY__EXPORT_INTERVAL_MILLIS=60000`
- `OBSERVABILITY__EXPORT_TIMEOUT_MILLIS=2000`

## Resource metadata and environment variables

Use **standard OpenTelemetry environment variables** for deployment metadata:

- `OTEL_SERVICE_NAME`
- `OTEL_RESOURCE_ATTRIBUTES`

Example:

```bash
OTEL_SERVICE_NAME=fastapi-saas-template
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production,service.version=1.2.0
```

Notes:

- Use `deployment.environment.name` (not deprecated `deployment.environment`).
- Application fallback for `service.name` remains: `OBSERVABILITY__SERVICE_NAME` or `APP__NAME`.
- `OTEL_RESOURCE_ATTRIBUTES` is the preferred place for deployment-specific metadata.

## OTLP headers and compression

Use standard OpenTelemetry exporter environment variables:

- `OTEL_EXPORTER_OTLP_HEADERS`
- `OTEL_EXPORTER_OTLP_METRICS_HEADERS`
- `OTEL_EXPORTER_OTLP_METRICS_COMPRESSION`

Example:

```bash
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>
OTEL_EXPORTER_OTLP_METRICS_HEADERS=Authorization=Bearer <token>
OTEL_EXPORTER_OTLP_METRICS_COMPRESSION=gzip
```

Security rules:

- OTLP headers may contain secrets.
- Do not log OTLP headers.
- Do not store OTLP headers in plain-string Pydantic settings.

## HTTP metric semantics

Current HTTP metrics:

- `http.server.request.duration`
- `http.server.requests.total`
- `http.server.errors.total`

Semantics:

- `http.server.request.duration` is the primary OpenTelemetry semantic-convention HTTP metric.
- `http.server.requests.total` and `http.server.errors.total` are **project-level custom helper metrics**.
- In future OTLP backends, request/error rates may be derived from histogram count, so helper counters can be revisited.
- Do not add duplicate HTTP counters through auto-instrumentation without an explicit architecture decision.

## RED and internal safety metrics

The project also records:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`
- `observability.recording_failures.total`

Failure recording is best-effort and must not break request flow.

## Local optional OTel Collector profile

A local collector profile is available via Docker Compose:

```bash
docker compose --profile observability up
```

Then configure app export, for example:

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics
```

Scope of this local profile:

- OTLP HTTP receiver (`4318`)
- debug/logging exporter output
- no Prometheus, no Grafana, no `/metrics` endpoint
