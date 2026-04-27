# Observability

## Current phase

- The project currently uses `opentelemetry-api` only.
- No OpenTelemetry SDK is initialized yet.
- No exporter is configured yet.
- No `/metrics` endpoint is exposed.
- Prometheus and Grafana are not connected at this phase.

## Current metrics foundation

The current foundation prepares rate-limit metrics via OpenTelemetry API instruments. Without SDK/exporter wiring, these instruments are effectively no-op at runtime but keep metric contracts stable.

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

- `request.scope.get("route").path`

Do not use:

- `request.url.path`
- raw path
- raw URL

If the route template is unavailable, use `"unknown"`.

## Future phases

P1:

- add HTTP RED middleware;
- use route templates only;
- keep labels low-cardinality.

P2:

- initialize OpenTelemetry SDK;
- add exporter;
- expose or export metrics for Prometheus-compatible collection;
- prepare Grafana dashboard.
