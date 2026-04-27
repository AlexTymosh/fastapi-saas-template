# Observability

## Current phase

This phase adds an **optional OpenTelemetry Collector-only verification path** for OTLP HTTP metrics export.

Current status:

- OpenTelemetry API instrumentation exists.
- Optional OpenTelemetry Metrics SDK lifecycle exists.
- Optional OTLP HTTP exporter configuration exists.
- Optional OTel Collector profile now exists for manual verification.
- No `/metrics` endpoint is exposed.
- Prometheus and Grafana are still not connected.

## Metrics foundation (unchanged)

Default behavior remains no-op and safe:

- `OBSERVABILITY__METRICS_ENABLED=false`
- `OBSERVABILITY__EXPORTER=none`
- no SDK/exporter initialization
- OpenTelemetry API instruments behave as no-op

When explicitly enabled (`metrics_enabled=true`, `exporter=otlp`), the app exports metrics via OTLP HTTP.

Current HTTP metric names:

- `http.server.requests.total`
- `http.server.errors.total`
- `http.server.request.duration`

Current rate-limit metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Internal observability failure self-metric:

- `observability.recording_failures.total`

## Optional collector profile

The collector is optional and does not start in the default stack.

Start default stack (collector is not started):

```bash
docker compose up
```

Start collector only through profile:

```bash
docker compose --profile observability up otel-collector
```

Collector config is intentionally minimal:

- receiver: OTLP HTTP (`0.0.0.0:4318`)
- exporter: `debug` with detailed verbosity
- pipeline: metrics only
- no traces pipeline
- no logs pipeline
- no Prometheus exporter

## OTLP endpoint configuration

### Host app + collector in Docker

Use `localhost` because the app process runs on the host machine:

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://localhost:4318/v1/metrics
```

### App container + collector container in Docker Compose network

Use the compose service name, not `localhost`:

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics
```

Important networking rule:

- `localhost` on host = developer machine.
- `localhost` inside app container = the app container itself.
- To reach collector from another container, use `otel-collector` service DNS name.

## OTLP HTTP path rule (`/v1/metrics`)

This project expects a **full metrics endpoint** in settings:

- `http://localhost:4318/v1/metrics`
- `http://otel-collector:4318/v1/metrics`

Do **not** use bare base URL (for this project):

- avoid `http://otel-collector:4318` unless your exporter setup appends signal path automatically.

Behavior verification for current dependency version (`opentelemetry-exporter-otlp-proto-http==1.28.2`):

- `OTLPMetricExporter(endpoint=...)` uses the provided `endpoint` as-is.
- Automatic `/v1/metrics` appending is used in fallback/env-based base endpoint handling, not when `endpoint=` is explicitly passed.

Because this code passes `endpoint=settings.observability.otlp_endpoint` directly, you must provide the full `/v1/metrics` path and avoid duplicated paths such as:

- `http://otel-collector:4318/v1/metrics/v1/metrics`

## Manual OTLP metrics verification

1. Start the collector:

```bash
docker compose --profile observability up otel-collector
```

2. Start the app with OTLP exporter enabled.

Host app example:

```bash
OBSERVABILITY__METRICS_ENABLED=true \
OBSERVABILITY__EXPORTER=otlp \
OBSERVABILITY__OTLP_ENDPOINT=http://localhost:4318/v1/metrics \
uvicorn app.main:app --reload
```

Docker app example:

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics
```

3. Trigger HTTP metrics:

```bash
curl http://localhost:8000/api/v1/health/live
```

4. Trigger rate-limit metrics using an existing rate-limited endpoint and valid local auth/test setup.

- Do not add insecure debug routes for this verification.
- Rate-limit metrics verification depends on having a reachable rate-limited endpoint and valid credentials/local setup.

5. Inspect collector logs and confirm metric names appear:

- `http.server.request.duration`
- `http.server.requests.total`
- `rate_limit.requests.total`
- `rate_limit.check.duration`

## Troubleshooting

- Collector not started:
  - run `docker compose --profile observability up otel-collector`.
- Wrong host in endpoint:
  - host app must use `localhost`;
  - app container must use `otel-collector`.
- Missing `/v1/metrics`:
  - set full endpoint path in `OBSERVABILITY__OTLP_ENDPOINT`.
- Duplicate `/v1/metrics`:
  - check endpoint construction and avoid concatenating path twice.
- Exporter timeout:
  - increase `OBSERVABILITY__OTLP_TIMEOUT_SECONDS` and verify collector readiness.

## Future phases (not in this phase)

- Prometheus-compatible collection path.
- Grafana dashboards.
- Alert rules.
