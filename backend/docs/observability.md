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

## HTTP RED metrics foundation

The project records HTTP RED-style metrics through OpenTelemetry API instruments.

Current HTTP metric names:

- `http.server.requests.total`
- `http.server.errors.total`
- `http.server.request.duration`

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

## Runtime safety

Observability must not change API behavior.

Metric recording failures are swallowed and logged as low-cardinality observability warnings.
The API response, status code, response body, and exception behavior remain unchanged.

Metrics failure logs must not include:

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
