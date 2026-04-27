# Observability

## Current phase

- OpenTelemetry API + SDK integration points are implemented.
- Observability is disabled by default (`OBSERVABILITY__METRICS_ENABLED=false`, `OBSERVABILITY__EXPORTER=none`).
- No `/metrics` endpoint is exposed.
- Prometheus and Grafana are intentionally not included in this phase.

## OpenTelemetry configuration model

### Application-level fallback service name

The app keeps an explicit fallback chain for `service.name`:

1. `OTEL_SERVICE_NAME` (standard OpenTelemetry env var, highest priority)
2. `OBSERVABILITY__SERVICE_NAME` (project setting fallback)
3. `APP__NAME` (final fallback)

### Deployment metadata via standard OTel env vars

Do not add a custom Pydantic field for every resource attribute. Use standard OpenTelemetry environment variables instead:

```bash
OTEL_SERVICE_NAME=fastapi-saas-template
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production,service.version=1.2.0
```

Notes:

- Use `deployment.environment.name` (not deprecated `deployment.environment`).
- `OTEL_RESOURCE_ATTRIBUTES` is the correct place for deployment metadata such as environment and version.

## OTLP headers and compression

Configure exporter headers/compression with standard OTel env vars:

```bash
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>
OTEL_EXPORTER_OTLP_METRICS_HEADERS=Authorization=Bearer <token>
OTEL_EXPORTER_OTLP_METRICS_COMPRESSION=gzip
```

Security rules:

- OTLP headers can contain secrets.
- Do not log OTLP header values.
- Do not expose OTLP headers via plain string Pydantic settings.

## HTTP metrics semantics

Current HTTP metrics:

- `http.server.request.duration`
- `http.server.requests.total`
- `http.server.errors.total`

Semantics:

- `http.server.request.duration` is the primary OpenTelemetry semantic-convention metric.
- `http.server.requests.total` and `http.server.errors.total` are project-level custom helper metrics.
- These custom counters may be removed later if backend validation confirms histogram `_count` is sufficient for request/error rates.
- Do not duplicate these metrics later with auto-instrumentation without an explicit design decision.

## Rate-limit metrics foundation

Current rate-limit metrics:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Allowed `rate_limit.result` values:

- `allowed`
- `blocked`
- `backend_error`
- `fail_open`

Low-cardinality attributes only:

- `rate_limit.policy`
- `rate_limit.result`
- `rate_limit.identifier_kind`
- `error.type`

## Local OTLP collector profile (optional)

Use the optional Docker Compose profile when you want to inspect OTLP exports locally:

```bash
docker compose --profile observability up
```

Then enable export from the app:

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics
```

The collector profile is local-only, uses OTLP HTTP (`4318`), and logs/debug-prints exported metrics. It does not add Prometheus, Grafana, or a scraping endpoint.
