# Rate limiting

## Current status

Rate limiting is implemented using the `limits` async Redis backend.

Current defaults:

- `RATE_LIMITING__ENABLED=false` by default;
- when disabled, no Redis rate-limiter runtime is initialised;
- when enabled, requests are evaluated by configured policy dependencies.

## Configuration

Primary settings:

- `RATE_LIMITING__ENABLED` — enables/disables rate limiting globally.
- `RATE_LIMITING__BACKEND` — backend type (`redis` in the current implementation).
- `RATE_LIMITING__REDIS_PREFIX` — key namespace prefix used for Redis counters.
- `RATE_LIMITING__TRUST_PROXY_HEADERS` — controls whether trusted proxy headers may be used for identifier fallback.
- `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS` — timeout for storage operations.
- `RATE_LIMITING__DEFAULT_FAIL_OPEN` — default fail-open mode for non-sensitive policies.
- `RATE_LIMITING__SENSITIVE_FAIL_OPEN` — fail-open mode override for sensitive policies.
- `REDIS__URL` — Redis connection URL.

Notes:

- `REDIS__URL` is required only when `RATE_LIMITING__ENABLED=true`.
- Startup is fail-fast when rate limiting is enabled and `REDIS__URL` is missing.

## Policy matrix

| Policy | Limit | Window | Fail mode | Purpose |
|---|---:|---|---|---|
| `invite_accept` | 5 | 5 minutes | fail-closed | Protect invite acceptance from brute force or token guessing. |
| `invite_create` | 20 | 1 hour | fail-closed | Protect invite creation from abuse. |

## Identifier strategy

- Authenticated requests are bucketed by authenticated principal identity.
- If principal identity is unavailable, fallback identifier kind may be used (for example, unknown/runtime-unavailable handling paths).
- Identifier values are hashed before being used as Redis keys.
- Raw user id, email, and IP address must not appear in metric attributes.
- `RATE_LIMITING__TRUST_PROXY_HEADERS` should remain `false` unless the service is behind a trusted proxy chain.

## Auth-before-rate-limit rule

For protected endpoints, authentication is resolved before rate-limit evaluation.

Expected behaviour:

- unauthenticated request returns `401` before rate-limit check;
- limiter does not build anonymous buckets for protected endpoints.

## Redis outage behaviour

Current behaviour is policy-driven:

- fail-closed policy + backend failure -> `503` with `error_code=rate_limiter_unavailable`;
- fail-open policy + backend failure -> request is allowed and a security warning is logged;
- runtime unavailable (runtime missing or limiter missing) -> `503` with `error_code=rate_limiter_unavailable`.

Backend failures emit dedicated metrics (`rate_limit.backend_errors.total`) and decision/duration metrics.

## Retry-After contract

When the request is over the configured limit:

- API returns `429` with `error_code=rate_limited`;
- response includes `Retry-After` header;
- `Access-Control-Expose-Headers: Retry-After` is included for browser/SPA clients;
- when precise Redis window stats are unavailable, fallback uses policy item expiry.

## Metrics contract

Emitted metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Allowed `rate_limit.result` values:

- `allowed`
- `blocked`
- `backend_error`
- `fail_open`
- `runtime_unavailable`

Allowed attributes:

- `rate_limit.policy`
- `rate_limit.result`
- `rate_limit.identifier_kind`
- `error.type`

Forbidden high-cardinality/sensitive values in metric attributes:

- raw user id;
- email;
- organisation id;
- request id;
- trace id;
- raw path;
- raw URL;
- IP address;
- token;
- Redis key;
- raw identifier value;
- hashed identifier value.

## OTLP verification status

Automated OTLP e2e verification currently covers:

- HTTP metrics export;
- rate-limit `allowed`/`blocked` export;
- backend error metric export for fail-closed path (`backend_error`);
- backend error metric export for fail-open path (`fail_open`);
- runtime unavailable path export (`runtime_unavailable`).

This phase intentionally does **not** include Prometheus/Grafana and does **not** expose a `/metrics` endpoint.

## Testing

Typical commands:

```bash
pytest tests/api/test_rate_limiting.py -q
pytest tests/api/test_rate_limiting_integration.py -q -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
pytest tests/observability -q
```
