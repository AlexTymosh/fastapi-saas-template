# Rate limiting

## Current status
Rate limiting is implemented for selected sensitive endpoints using `limits` with async Redis backend.

- Status: implemented for protected invite flows.
- Default mode: disabled (`RATE_LIMITING__ENABLED=false`).
- When disabled, limiter dependencies are no-op.

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

Rules:
- `REDIS__URL` is required only when `RATE_LIMITING__ENABLED=true`.
- If enabled without `REDIS__URL`, startup fails fast.

## Policy matrix

| Policy | Limit | Window | Fail mode | Purpose |
|---|---:|---|---|---|
| `invite_accept` | 5 | 5 minutes | fail-closed | Protect invite acceptance from brute force/token guessing |
| `invite_create` | 20 | 1 hour | fail-closed | Protect invite creation from abuse |

## Protected endpoint matrix

| Method | Endpoint | Policy |
|---|---|---|
| POST | `/api/v1/organisations/{organisation_id}/invites` | `invite_create` |
| POST | `/api/v1/invites/accept` | `invite_accept` |

## Identifier strategy
- Authenticated requests are bucketed by principal identity.
- Identifier kind is tracked via `rate_limit.identifier_kind` for observability.
- Identifier values are hashed before becoming Redis keys.
- Raw user ID/email/IP must not appear in logs/metrics.
- Keep `RATE_LIMITING__TRUST_PROXY_HEADERS=false` unless proxy chain is explicitly trusted.

## Auth-before-rate-limit rule
For protected endpoints:

- authentication is resolved before limiter checks;
- unauthenticated requests return `401` first;
- no anonymous buckets are created for protected routes.

## Redis outage behaviour
Runtime/backend failures follow policy fail mode.

- **Fail-closed** (`fail_open=false`): return `503` (`error_code=rate_limiter_unavailable`).
- **Fail-open** (`fail_open=true`): allow request, emit backend-error metric, log security warning.
- **Runtime unavailable** (limiter/runtime missing): return `503` (`error_code=rate_limiter_unavailable`).

In all backend failure paths, observability metrics are emitted.

## Retry-After contract
Over-limit responses must:

- return `429`;
- include `Retry-After`;
- include `Access-Control-Expose-Headers: Retry-After`;
- use policy-expiry fallback if Redis window stats are unavailable.

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

Forbidden high-cardinality/sensitive values:

- raw user id/email/IP;
- organisation id;
- request id/trace id;
- raw path/URL;
- token;
- Redis key;
- identifier raw/hashed value.

## OTLP verification status
Current e2e OTLP coverage validates export through OTel Collector debug logs for:

- HTTP metrics;
- rate-limit `allowed` and `blocked` decisions;
- backend error paths (`backend_error`, `fail_open`, `runtime_unavailable`) with `error.type`.

Prometheus/Grafana dashboards are out of scope for this phase, and `/metrics` is not exposed.

## Testing commands
Run from `backend/`:

```bash
pytest tests/api/test_rate_limiting.py -q
pytest tests/api/test_rate_limiting_integration.py -q -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```

## Acceptance checklist
- [ ] Default local/test startup does not require Redis.
- [ ] Enabling rate limiting without Redis fails fast.
- [ ] Invite create endpoint is rate limited.
- [ ] Invite accept endpoint is rate limited.
- [ ] `401` happens before limiter for unauthenticated protected requests.
- [ ] `429` includes Problem Details payload.
- [ ] `429` includes `Retry-After`.
- [ ] Over-limit requests do not execute endpoint body.
- [ ] Over-limit requests do not perform DB I/O.
- [ ] Fail-closed backend outage returns `503`.
- [ ] Rate-limit metrics are recorded.
- [ ] Sensitive endpoint protection is covered by tests.