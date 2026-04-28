# Observability

## Current phase

This repository is now in the **OTel Collector-only verification** phase for metrics export.

What is implemented in this phase:

- OpenTelemetry API instrumentation for HTTP RED and rate-limit metrics.
- Optional OpenTelemetry Metrics SDK lifecycle.
- Optional OTLP HTTP metric exporter.
- Optional Docker Compose profile with **OpenTelemetry Collector + debug exporter**.

What is still intentionally not implemented:

- no Prometheus;
- no Grafana;
- no `/metrics` endpoint.

## Default behavior (unchanged)

By default, metrics export remains disabled.

- `OBSERVABILITY__METRICS_ENABLED=false`
- `OBSERVABILITY__EXPORTER=none`
- OTLP endpoint is not required.
- Application startup does not require an OTel Collector.

`OBSERVABILITY__OTLP_ENDPOINT` is required only when both are true:

- `OBSERVABILITY__METRICS_ENABLED=true`
- `OBSERVABILITY__EXPORTER=otlp`

## Optional OTel Collector profile

Compose includes an optional service profile `observability`.

Start only collector:

```bash
docker compose --profile observability up otel-collector
```

Start full stack with optional collector profile:

```bash
docker compose --profile observability up
```

Default command still does not start collector:

```bash
docker compose up
```

## Collector configuration

Collector config is intentionally minimal and metrics-only:

- OTLP HTTP receiver on `0.0.0.0:4318`;
- debug exporter with detailed verbosity;
- metrics pipeline only.

No trace pipeline and no logs pipeline are configured in this phase.

## OTLP endpoint: host machine vs Docker network

Use different OTLP endpoint hostnames depending on where the app process runs.

### A) App runs on host machine, collector runs in Docker

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://localhost:4318/v1/metrics
```

### B) App runs inside Docker Compose network

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics
```

Important network rule:

- `localhost` on the host points to the developer machine;
- `localhost` inside the `app` container points to the `app` container itself;
- to reach collector from another container, use service DNS name `otel-collector`.

## OTLP HTTP endpoint path rule (`/v1/metrics`)

For this project, `OTLPMetricExporter(endpoint=...)` must receive the **full metrics endpoint**, including `/v1/metrics`.

Use:

- `http://localhost:4318/v1/metrics`
- `http://otel-collector:4318/v1/metrics`

Do not use a bare base URL such as `http://otel-collector:4318` unless your exporter setup is explicitly designed to append the signal path.

### Verified behavior reference

Repository dependency pins `opentelemetry-exporter-otlp-proto-http==1.28.2`.
In upstream source for this version, `OTLPMetricExporter(endpoint=...)` uses the provided endpoint as-is, while automatic `/v1/metrics` append applies only to fallback path resolution when endpoint is not passed explicitly:

- https://raw.githubusercontent.com/open-telemetry/opentelemetry-python/v1.28.2/exporter/opentelemetry-exporter-otlp-proto-http/src/opentelemetry/exporter/otlp/proto/http/metric_exporter/__init__.py

To avoid double path issues (for example `/v1/metrics/v1/metrics`), this project expects explicit full metrics endpoint configuration.

## Metrics currently instrumented

HTTP RED metrics:

- `http.server.requests.total`
- `http.server.errors.total`
- `http.server.request.duration`

Rate-limit metrics:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Route labels use route templates from FastAPI routes, not raw paths.

## Manual OTLP metrics verification

1. Start collector profile:

```bash
docker compose --profile observability up otel-collector
```

2. Start app with OTLP metrics enabled.

Host app example:

```bash
OBSERVABILITY__METRICS_ENABLED=true \
OBSERVABILITY__EXPORTER=otlp \
OBSERVABILITY__OTLP_ENDPOINT=http://localhost:4318/v1/metrics \
uvicorn app.main:app --reload
```

Docker app example (`compose.yaml` environment):

```bash
OBSERVABILITY__METRICS_ENABLED=true
OBSERVABILITY__EXPORTER=otlp
OBSERVABILITY__OTLP_ENDPOINT=http://otel-collector:4318/v1/metrics
```

3. Trigger HTTP metrics:

```bash
curl http://localhost:8000/api/v1/health/live
```

4. Trigger rate-limit metrics using an existing rate-limited endpoint with valid auth/test setup.

Rate-limit verification requires existing protected/rate-limited routes and valid credentials in local/dev setup. No insecure debug routes are added in this phase.

5. Check collector logs for expected metric names:

- `http.server.request.duration`
- `http.server.requests.total`
- `rate_limit.requests.total`
- `rate_limit.check.duration`

## Automated OTLP verification

The test suite includes automated OTLP export verification using an ephemeral
OpenTelemetry Collector started via Testcontainers.

- no Prometheus or Grafana required;
- no `/metrics` endpoint required;
- validation is based on Collector `debug` exporter logs;
- test performs a real request through the app lifespan and waits for exported
  metric names in Collector logs.

Run the automated check:

```bash
pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```

## Troubleshooting

- **Collector not started**: start `docker compose --profile observability up otel-collector`.
- **Wrong host in endpoint**:
  - host app -> `localhost`;
  - container app -> `otel-collector`.
- **Missing `/v1/metrics`**: exporter may post to wrong URL and fail.
- **Duplicate `/v1/metrics`**: fix endpoint to a single full path.
- **Exporter timeout**: adjust `OBSERVABILITY__OTLP_TIMEOUT_SECONDS` and verify collector is reachable.
- **No rate-limit metrics**: ensure a rate-limited endpoint is actually called with valid auth/test setup.
