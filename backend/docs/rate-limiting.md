# Rate limiting

## Current status

Rate limiting is implemented with the `limits` async Redis backend and is **disabled by default**.

When disabled, rate-limit dependencies are effectively no-op and requests proceed to regular auth/business checks.

## Configuration

Primary settings:

- `RATE_LIMITING__ENABLED`
- `RATE_LIMITING__BACKEND`
- `RATE_LIMITING__REDIS_PREFIX`
- `RATE_LIMITING__TRUST_PROXY_HEADERS`
- `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS`
- `RATE_LIMITING__DEFAULT_FAIL_OPEN`
- `RATE_LIMITING__SENSITIVE_FAIL_OPEN`
- `REDIS__URL`

Notes:

- `REDIS__URL` is required only when `RATE_LIMITING__ENABLED=true`.
- If rate limiting is enabled and `REDIS__URL` is missing, startup fails fast.

## Policy matrix

| Policy | Limit | Window | Fail mode | Purpose |
|---|---:|---|---|---|
| `invite_accept` | 5 | 5 minutes | fail-closed | Protect invite acceptance from brute force/token guessing |
| `invite_create` | 20 | 1 hour | fail-closed | Protect invite creation from abuse |

## Identifier strategy

- Authenticated requests are bucketed by principal identity.
- Identifier kind is tracked as an attribute (`rate_limit.identifier_kind`) for observability.
- Identifier values are hashed before use as Redis keys.
- Raw user id/email/IP must not appear in metrics or logs.
- `RATE_LIMITING__TRUST_PROXY_HEADERS` should remain `false` unless traffic is known to come through a trusted proxy chain.

## Auth-before-rate-limit rule

For protected endpoints, authentication is resolved before rate-limit checks.

- Unauthenticated requests return `401` first.
- This avoids creating anonymous buckets for protected routes.

## Redis outage behaviour

Backend failures are handled by policy mode:

- **Fail-closed** (`fail_open=false`): return `503` with `error_code=rate_limiter_unavailable`.
- **Fail-open** (`fail_open=true`): allow request, emit backend error metric, and log a security warning.
- **Runtime unavailable** (runtime missing or limiter missing): return `503` with `error_code=rate_limiter_unavailable`.

In all backend failure scenarios, observability metrics are emitted.

## Retry-After contract

When a request is over limit:

- response status is `429`;
- response includes `Retry-After`;
- response includes `Access-Control-Expose-Headers: Retry-After` for browser/SPA visibility;
- if Redis window stats are unavailable, fallback uses policy item expiry.

## Metrics contract

Metric names:

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

Forbidden high-cardinality/sensitive attribute values:

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
- identifier value;
- hashed identifier value.

## OTLP verification status

Current automated OTLP e2e coverage validates export via OTel Collector debug logs for:

- HTTP metrics;
- rate-limit allowed and blocked decisions;
- rate-limit backend errors (`backend_error`, `fail_open`, `runtime_unavailable`), including `error.type`.

Prometheus/Grafana are intentionally out of scope in this phase, and `/metrics` is not exposed.

## Testing

From `backend/`:

```bash
pytest tests/api/test_rate_limiting.py -q
pytest tests/api/test_rate_limiting_integration.py -q -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```
