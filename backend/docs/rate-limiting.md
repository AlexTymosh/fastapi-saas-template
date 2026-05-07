# Rate limiting

## Current status

Rate limiting is implemented for sensitive authenticated endpoint groups using `limits` with an async Redis backend.

- Status: implemented for authenticated defaults, tenant reads/writes, organisation creation, invite flows, platform reads, audit reads, and platform writes.
- Default mode: disabled (`RATE_LIMITING__ENABLED=false`).
- When disabled, limiter dependencies are no-op.
- Health, docs, OpenAPI, and static endpoints are intentionally not protected by this application-level limiter; production deployments should still use edge/WAF controls for broad traffic shaping.

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
| `authenticated_default` | 120 | 1 minute | fail-open | Low-risk authenticated reads, currently `/users/me`; availability is preferred if Redis is degraded. |
| `tenant_read` | 120 | 1 minute | fail-open | Tenant read/list endpoints such as organisation details, directory, and membership listing; availability is preferred for normal tenant browsing. |
| `tenant_write` | 30 | 1 minute | fail-closed | Tenant mutations such as organisation updates/deletes and membership role/removal operations; Redis failures block writes to avoid unthrottled abuse. |
| `organisation_create` | 5 | 1 hour | fail-closed | Organisation onboarding/create abuse prevention; Redis failures block creation to protect tenant namespace and onboarding resources. |
| `invite_accept` | 5 | 5 minutes | fail-closed | Invite acceptance token brute-force/guessing protection. |
| `invite_create` | 20 | 1 hour | fail-closed | Invite creation and resend abuse prevention. |
| `invite_mutation` | 30 | 1 hour | fail-closed | Admin invite mutations that are not token brute-force paths, currently invite revoke. |
| `platform_read` | 60 | 1 minute | fail-closed | Platform user, organisation, and staff list/detail enumeration reduction. |
| `audit_read` | 30 | 1 minute | fail-closed | Sensitive platform audit listing and filtering protection, including full and limited views. |
| `platform_write` | 30 | 1 minute | fail-closed | Sensitive platform user/organisation writes with a valid platform token. |
| `platform_staff_write` | 10 | 1 minute | fail-closed | High-impact platform staff management writes. |

## Protected endpoint matrix

| Method | Endpoint | Policy |
|---|---|---|
| GET | `/api/v1/users/me` | `authenticated_default` |
| POST | `/api/v1/organisations` | `organisation_create` |
| GET | `/api/v1/organisations/{organisation_id}` | `tenant_read` |
| GET | `/api/v1/organisations/{organisation_id}/directory` | `tenant_read` |
| GET | `/api/v1/organisations/{organisation_id}/memberships` | `tenant_read` |
| PATCH | `/api/v1/organisations/{organisation_id}` | `tenant_write` |
| DELETE | `/api/v1/organisations/{organisation_id}` | `tenant_write` |
| PATCH | `/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role` | `tenant_write` |
| DELETE | `/api/v1/organisations/{organisation_id}/memberships/{membership_id}` | `tenant_write` |
| POST | `/api/v1/organisations/{organisation_id}/invites` | `invite_create` |
| POST | `/api/v1/invites/accept` | `invite_accept` |
| DELETE | `/api/v1/organisations/{organisation_id}/invites/{invite_id}` | `invite_mutation` |
| POST | `/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend` | `invite_create` |
| GET | `/api/v1/platform/users` | `platform_read` |
| GET | `/api/v1/platform/users/{user_id}` | `platform_read` |
| POST | `/api/v1/platform/users/{user_id}/suspend` | `platform_write` |
| POST | `/api/v1/platform/users/{user_id}/restore` | `platform_write` |
| GET | `/api/v1/platform/organisations` | `platform_read` |
| GET | `/api/v1/platform/organisations/{organisation_id}` | `platform_read` |
| POST | `/api/v1/platform/organisations/{organisation_id}/suspend` | `platform_write` |
| POST | `/api/v1/platform/organisations/{organisation_id}/restore` | `platform_write` |
| PATCH | `/api/v1/platform/organisations/{organisation_id}` | `platform_write` |
| GET | `/api/v1/platform/staff` | `platform_read` |
| POST | `/api/v1/platform/staff` | `platform_staff_write` |
| PATCH | `/api/v1/platform/staff/{staff_id}/role` | `platform_staff_write` |
| POST | `/api/v1/platform/staff/{staff_id}/suspend` | `platform_staff_write` |
| POST | `/api/v1/platform/staff/{staff_id}/restore` | `platform_staff_write` |
| GET | `/api/v1/platform/audit-events/limited` | `audit_read` |
| GET | `/api/v1/platform/audit-events` | `audit_read` |

## Identifier strategy

- Authenticated requests are bucketed by principal identity.
- Identifier kind is tracked via `rate_limit.identifier_kind` for observability.
- Identifier values are hashed before becoming Redis keys.
- Raw user ID/email/IP must not appear in logs/metrics.
- Keep `RATE_LIMITING__TRUST_PROXY_HEADERS=false` unless proxy chain is explicitly trusted.

## Auth-before-rate-limit rule

For protected endpoints:

- authentication is resolved before limiter checks;
- unauthenticated requests return `401` before any limiter hit;
- no anonymous buckets are created for protected routes.

For platform read/write helpers, rate limiting runs after authentication and before platform permission/database work where the dependency boundary allows it. Platform writes keep the stricter transaction boundary: the limiter check happens before opening the write transaction.

## Redis outage behaviour

Runtime/backend failures follow policy fail mode.

- **Fail-closed** (`fail_open=false`): return `503` (`error_code=rate_limiter_unavailable`). Tenant writes, organisation creation, invite mutation/accept/create, platform reads, audit reads, and platform writes are fail-closed so Redis/rate-limiter outages block sensitive operations instead of allowing unthrottled abuse.
- **Fail-open** (`fail_open=true`): allow request, emit backend-error metric, log security warning. This is limited to lower-risk authenticated/tenant read paths where availability is preferred.
- **Runtime unavailable** (limiter/runtime missing): return `503` (`error_code=rate_limiter_unavailable`).

In all backend failure paths, observability metrics are emitted.

## Retry-After contract

Over-limit responses must:

- return `429`;
- use Problem Details with `application/problem+json` and `error_code=rate_limited`;
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

## Testing coverage

Endpoint-level coverage tests inspect FastAPI dependencies for the expected policy metadata. Behaviour tests cover over-limit `429` before service execution for tenant write, audit read, and organisation creation paths, plus unauthenticated `401` before limiter hits.

Platform write policies remain covered by fast fake-limiter API regression tests and Redis/Testcontainers integration tests. The fake tests keep fail-closed and transaction-boundary behaviour cheap to validate, while the integration tests exercise `limits`, async Redis storage, real Redis windows, and real over-limit responses for `platform_write` and `platform_staff_write`.

## Testing commands

Run from `backend/`:

```bash
pytest -q tests/rate_limit/test_policy_registry.py
pytest -q tests/rate_limit/test_endpoint_protection.py
pytest -q tests/api/test_rate_limiting.py
pytest -q tests/platform/test_platform_write_rate_limiting.py
pytest -q tests/platform/test_platform_write_rate_limiting_integration.py -m integration -rs
pytest tests/api/test_rate_limiting_integration.py -q -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```

## Acceptance checklist

- [x] Default local/test startup does not require Redis.
- [x] Enabling rate limiting without Redis fails fast.
- [x] Authenticated default endpoint is rate limited.
- [x] Tenant read/write/create endpoints are rate limited.
- [x] Invite create endpoint is rate limited.
- [x] Invite accept endpoint is rate limited.
- [x] Invite revoke endpoint is rate limited.
- [x] Platform read/list/detail endpoints are rate limited.
- [x] Platform audit full and limited list endpoints are rate limited.
- [x] Platform write endpoints remain rate limited.
- [x] `401` happens before limiter for unauthenticated protected requests.
- [x] `429` includes Problem Details payload.
- [x] `429` includes `Retry-After`.
- [x] Newly protected endpoints document `429`/`503` Problem Details responses.
- [x] Over-limit requests do not execute endpoint body/service work in focused tests.
- [x] Fail-closed policies return `503` when the limiter backend is unavailable.
- [x] Fail-open policies allow requests and emit backend-error observability.
- [x] No raw identifier is logged or recorded as metric attribute by the limiter path.
- [x] Health/docs/static endpoints are intentionally not protected by this app-level limiter.
