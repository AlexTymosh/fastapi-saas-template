# Rate limiting

## Current status

Rate limiting is implemented for sensitive authenticated endpoint groups using route-level FastAPI dependencies and `limits` with an async Redis backend. It is intentionally not implemented as global FastAPI/Starlette middleware because protected routes rely on authenticated principal resolution, per-endpoint policy selection, route-level policy matrix tests, and auth → rate-limit → DB dependency ordering.

- Status: implemented for authenticated user reads, tenant read/write flows, organisation creation, invite flows, platform read/list/detail flows, platform audit listing, and platform write operations.
- Default mode: disabled (`RATE_LIMITING__ENABLED=false`).
- Policy defaults are declared once as policy specs; effective runtime policies are resolved from settings during lifespan startup.
- When disabled, limiter dependencies are no-op, but effective policy resolution still happens for startup validation and logging.
- Health and docs/static endpoints are intentionally not protected by this app-level limiter; keep edge/WAF controls for public unauthenticated traffic.

## Configuration

Primary settings:

- `RATE_LIMITING__ENABLED`
- `RATE_LIMITING__BACKEND`
- `RATE_LIMITING__REDIS_PREFIX`
- `RATE_LIMITING__TRUST_PROXY_HEADERS`
- `RATE_LIMITING__MODE` (`normal`, `strict`, `relaxed`, `panic`)
- `RATE_LIMITING__POLICIES__<POLICY_NAME>__LIMIT`
- `RATE_LIMITING__POLICIES__<POLICY_NAME>__WINDOW_SECONDS`
- `RATE_LIMITING__POLICIES__<POLICY_NAME>__FAIL_OPEN`
- `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS`
- `REDIS__URL`

Rules:

- `REDIS__URL` is required only when `RATE_LIMITING__ENABLED=true`.
- If enabled without `REDIS__URL`, startup fails fast after effective policy resolution.
- Unknown policy override names fail fast, for example `RATE_LIMITING__POLICIES__UNKNOWN_POLICY__LIMIT=10`.
- Invalid override limits/windows fail fast because values must be greater than zero.
- The old global default/fail-open settings are intentionally not present; operators override explicit named policies instead.

Example override:

```env
RATE_LIMITING__MODE=strict
RATE_LIMITING__POLICIES__TENANT_WRITE__LIMIT=20
RATE_LIMITING__POLICIES__TENANT_WRITE__WINDOW_SECONDS=60
RATE_LIMITING__POLICIES__TENANT_WRITE__FAIL_OPEN=false
```

Mode precedence is: policy spec defaults → mode transformation → explicit per-policy override. Panic mode applies one final safety guard so sensitive and critical policies cannot become fail-open even if an override sets `FAIL_OPEN=true`.

Mode behaviour:

| Mode | Behaviour | Production rule |
|---|---|---|
| `normal` | Use policy defaults plus explicit overrides. | Allowed |
| `strict` | Halve default limits globally, keep windows, and never make fail-open more permissive. Explicit policy overrides still win. | Allowed |
| `relaxed` | Double default limits, keep windows. | Rejected in `prod` |
| `panic` | Halve sensitive limits, quarter critical limits, and force sensitive/critical policies fail-closed. | Allowed; config-level only, no runtime admin/UI switch in this PR |

## Policy matrix

| Policy | Limit | Window | Fail mode | Purpose |
|---|---:|---|---|---|
| `authenticated_default` | 120 | 1 minute | fail-open | Low-risk authenticated reads such as `/users/me` |
| `tenant_read` | 120 | 1 minute | fail-open | Tenant read, directory, and membership listing endpoints |
| `tenant_write` | 30 | 1 minute | fail-closed | Tenant mutations and membership management |
| `organisation_create` | 5 | 1 hour | fail-closed | Protect organisation creation/onboarding from abuse |
| `invite_accept` | 5 | 5 minutes | fail-closed | Protect invite acceptance from brute force/token guessing |
| `invite_create` | 20 | 1 hour | fail-closed | Protect invite creation from abuse |
| `invite_mutation` | 30 | 1 hour | fail-closed | Protect invite revoke/resend/admin invite operations |
| `platform_read` | 60 | 1 minute | fail-closed | Reduce platform user/organisation/staff enumeration and listing abuse |
| `audit_read` | 30 | 1 minute | fail-closed | Critical protection for full and limited audit listing/filtering |
| `platform_write` | 30 | 1 minute | fail-closed | Protect sensitive platform user/organisation writes from abuse with a valid platform token |
| `platform_staff_write` | 10 | 1 minute | fail-closed | Protect high-impact platform staff management writes |

Fail-open is reserved for low-risk authenticated reads where availability is preferred and backend errors are still recorded. Tenant writes, organisation creation, invite administration, platform reads, audit reads, and platform writes are fail-closed because abuse impact or enumeration risk is higher. Effective fail-open/fail-closed behaviour is resolved from the default spec, selected mode, explicit override, and the panic-mode safety guard.

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
| POST | `/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend` | `invite_mutation` |
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
- unauthenticated requests return `401` first;
- no anonymous buckets are created for protected routes.

## Redis outage behaviour

Runtime/backend failures follow policy fail mode.

- **Fail-closed** (`fail_open=false`): return `503` (`error_code=rate_limiter_unavailable`). Sensitive tenant writes, organisation create, invite administration, audit/platform reads, and platform writes block when Redis/rate-limiter is unavailable.
- **Fail-open** (`fail_open=true`): allow request, emit backend-error metric, log security warning. This is limited to low-risk authenticated and tenant reads.
- **Runtime unavailable** (limiter/runtime missing): return `503` (`error_code=rate_limiter_unavailable`).

In all backend failure paths, observability metrics are emitted.

## Retry-After contract

Over-limit responses must:

- return `429`;
- use Problem Details with `application/problem+json`;
- include `Retry-After`;
- include `Access-Control-Expose-Headers: Retry-After`;
- use policy-expiry fallback if Redis window stats are unavailable.

Newly protected endpoints declare the `429` and fail-closed `503` Problem Details responses in OpenAPI via `RATE_LIMIT_ERROR_RESPONSES`.

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

Settings and policy registry tests assert every named policy is registered, effective defaults preserve existing runtime behaviour, per-policy overrides are parsed and applied, invalid/unknown overrides fail fast, `relaxed` is rejected in production, and `panic` is accepted in production while forcing sensitive/critical policies fail-closed. Endpoint-protection tests introspect FastAPI route dependencies and verify sensitive route groups carry the expected endpoint-level policy metadata while health endpoints remain unprotected. Fake-limiter API tests cover settings-aware effective thresholds, `429` Problem Details, `Retry-After`, unauthenticated `401` before limiter checks, and blocking before service/DB execution for tenant write, audit read, and organisation create paths.

Platform write policies remain covered by both fast fake-limiter API regression tests and Redis/Testcontainers integration tests. The fake tests keep fail-closed and transaction-boundary behaviour cheap to validate, while the integration tests exercise `limits`, async Redis storage, real Redis windows, and real over-limit responses for `platform_write` and `platform_staff_write`.

## Testing commands

Run from `backend/`:

```bash
pytest -q tests/config/test_settings.py
pytest -q tests/rate_limit/test_policy_registry.py
pytest -q tests/rate_limit/test_endpoint_protection.py
pytest -q tests/api/test_rate_limiting.py
pytest -q tests/platform/test_platform_write_rate_limiting.py
pytest -q tests/platform/test_platform_write_rate_limiting_integration.py -m integration -rs
pytest -q tests/api/test_rate_limiting_integration.py -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```

## Acceptance checklist

- [x] Default local/test startup does not require Redis.
- [x] Enabling rate limiting without Redis fails fast.
- [x] Policy defaults are declared once and effective runtime policies are settings-aware.
- [x] Per-policy overrides are validated and applied through nested env settings.
- [x] Config-level `panic` mode exists; runtime/admin panic switching is intentionally out of scope.
- [x] Invite create endpoint is rate limited.
- [x] Invite accept endpoint is rate limited.
- [x] Invite revoke/resend admin operations are rate limited.
- [x] Authenticated `/users/me` is rate limited.
- [x] Tenant read/write/create endpoint groups are rate limited.
- [x] Platform read/list/detail endpoint groups are rate limited.
- [x] Platform full and limited audit listing endpoints are rate limited.
- [x] Health/docs/static endpoints are not protected by this app-level limiter.
- [x] `401` happens before limiter for unauthenticated protected requests.
- [x] `429` includes Problem Details payload.
- [x] `429` includes `Retry-After`.
- [x] Over-limit requests do not execute endpoint body.
- [x] Over-limit requests do not perform DB I/O for newly covered sensitive paths.
- [x] Fail-closed backend outage returns `503` Problem Details.
- [x] Observability uses low-cardinality policy/result/identifier-kind/error-type labels only.
