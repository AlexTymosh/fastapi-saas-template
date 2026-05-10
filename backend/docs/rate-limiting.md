# Rate limiting

## Current status

Rate limiting is implemented for sensitive authenticated endpoint groups using `limits` with an async Redis backend.

- Status: implemented for authenticated user reads, tenant read/write flows, organisation creation, layered invite anti-abuse flows, platform read/list/detail flows, platform audit listing, and platform write operations.
- Default enablement: disabled (`RATE_LIMITING__ENABLED=false`).
- Policy mode default: `normal`.
- When disabled, limiter dependencies are no-op, but policy resolution still uses the same settings-aware registry so startup can report the effective configuration.
- Health and docs/static endpoints are intentionally not protected by this app-level limiter; keep edge/WAF controls for public unauthenticated traffic.
- The limiter is intentionally route-level and dependency-based, not FastAPI/Starlette middleware-based. This preserves authenticated principal resolution, per-endpoint policy selection, policy matrix tests, and the auth -> rate-limit -> database dependency ordering.

## Configuration

Primary settings:

- `RATE_LIMITING__ENABLED`
- `RATE_LIMITING__BACKEND`
- `RATE_LIMITING__REDIS_PREFIX`
- `RATE_LIMITING__TRUST_PROXY_HEADERS`
- `RATE_LIMITING__IDENTIFIER_SECRET`
- `RATE_LIMITING__MODE` (`normal`, `strict`, `relaxed`, `panic`)
- `RATE_LIMITING__POLICIES__<POLICY_NAME>__LIMIT`
- `RATE_LIMITING__POLICIES__<POLICY_NAME>__WINDOW_SECONDS`
- `RATE_LIMITING__POLICIES__<POLICY_NAME>__FAIL_OPEN`
- `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS`
- `REDIS__URL`

Rules:

- `REDIS__URL` is required only when `RATE_LIMITING__ENABLED=true`.
- `RATE_LIMITING__IDENTIFIER_SECRET` is required when `RATE_LIMITING__ENABLED=true` and must be at least 32 characters. It is used only for rate-limit identifier HMAC bucket keys and must not match Keycloak, client, outbox/Fernet, database, Redis, or other application secrets.
- If enabled without `REDIS__URL` or `RATE_LIMITING__IDENTIFIER_SECRET`, startup fails fast.
- Unknown policy override names fail fast, for example `RATE_LIMITING__POLICIES__UNKNOWN_POLICY__LIMIT=10`.
- Invalid override limits/windows fail fast. Supported runtime windows are 60 seconds, 300 seconds, 3600 seconds, and 86400 seconds.
- `relaxed` mode is rejected in production.
- `panic` mode is accepted in production and is config-level only in this change; there is no runtime/admin-UI panic switch.

Policy defaults are declared once in `backend/app/core/rate_limit/policies.py` as declarative specs. Startup resolves effective runtime policies from those specs, the selected mode, and explicit per-policy overrides. Precedence is:

1. policy spec defaults;
2. mode transformation;
3. explicit per-policy override.

Exception: in `panic` mode, sensitive and critical policies always remain fail-closed even if an override attempts `FAIL_OPEN=true`.

Generate a strong identifier secret with OpenSSL:

```bash
openssl rand -hex 32
```

Do not hardcode weak placeholder values and do not commit real secrets. Local/dev environments may use a locally generated value. Staging and production should inject the value through a secrets manager or environment injection. Rotating `RATE_LIMITING__IDENTIFIER_SECRET` changes the HMAC output and resets active limiter buckets; this is acceptable for rate limiting, but rotation is best done during a low-traffic window or as part of compromise response. No dual-read/dual-write rotation is implemented.

Example override:

```bash
RATE_LIMITING__POLICIES__TENANT_WRITE__LIMIT=20
RATE_LIMITING__POLICIES__TENANT_WRITE__WINDOW_SECONDS=60
RATE_LIMITING__POLICIES__TENANT_WRITE__FAIL_OPEN=false
```

Mode behaviour:

| Mode | Behaviour | Production |
|---|---|---|
| `normal` | Use safe defaults plus explicit overrides. | Allowed |
| `strict` | Halve default limits before overrides; windows are unchanged; fail-open does not become more permissive. | Allowed |
| `relaxed` | Double default limits before overrides; windows are unchanged. | Rejected |
| `panic` | Halve sensitive default limits, quarter critical default limits, and force sensitive/critical fail-closed after overrides. | Allowed |

## Policy matrix

| Policy | Default limit | Default window | Default fail mode | Sensitivity | Purpose |
|---|---:|---|---|---|---|
| `authenticated_default` | 120 | 1 minute | fail-open | normal | Low-risk authenticated reads such as `/users/me` |
| `tenant_read` | 120 | 1 minute | fail-open | normal | Tenant read, directory, and membership listing endpoints |
| `tenant_write` | 30 | 1 minute | fail-closed | sensitive | Tenant mutations and membership management |
| `organisation_create` | 5 | 1 hour | fail-closed | critical | Protect organisation creation/onboarding from abuse |
| `invite_accept` | 5 | 5 minutes | fail-closed | critical | Protect invite acceptance from brute force/token guessing |
| `invite_create` | 20 | 1 hour | fail-closed | sensitive | Protect invite creation by authenticated actor |
| `invite_create_organisation` | 50 | 1 hour | fail-closed | sensitive | Limit organisation-wide invite creation bursts |
| `invite_create_organisation_daily` | 200 | 1 day | fail-closed | critical | Cap daily organisation-wide invite creation pressure |
| `invite_create_target_email` | 3 | 1 day | fail-closed | critical | Limit repeated invite creation to one email within one organisation |
| `invite_create_target_domain` | 50 | 1 day | fail-closed | sensitive | Limit invite creation to one target domain within one organisation |
| `invite_mutation` | 30 | 1 hour | fail-closed | sensitive | Protect invite revoke/resend/admin invite operations |
| `invite_resend_invite` | 5 | 1 hour | fail-closed | sensitive | Limit repeated resend attempts for one invite |
| `invite_resend_organisation_daily` | 200 | 1 day | fail-closed | sensitive | Cap daily organisation-wide resend pressure |
| `platform_read` | 60 | 1 minute | fail-closed | sensitive | Reduce platform user/organisation/staff enumeration and listing abuse |
| `audit_read` | 30 | 1 minute | fail-closed | critical | Protect sensitive full and limited audit listing/filtering |
| `platform_write` | 30 | 1 minute | fail-closed | critical | Protect sensitive platform user/organisation writes from abuse with a valid platform token |
| `platform_staff_write` | 10 | 1 minute | fail-closed | critical | Protect high-impact platform staff management writes |

Fail-open is reserved for low-risk authenticated reads where availability is preferred and backend errors are still recorded. Tenant writes, organisation creation, invite administration, platform reads, audit reads, and platform writes are fail-closed because abuse impact or enumeration risk is higher.

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
| POST | `/api/v1/organisations/{organisation_id}/invites` | layered `invite_create`, `invite_create_organisation`, `invite_create_organisation_daily`, `invite_create_target_email`, `invite_create_target_domain` |
| POST | `/api/v1/invites/accept` | `invite_accept` |
| DELETE | `/api/v1/organisations/{organisation_id}/invites/{invite_id}` | `invite_mutation` |
| POST | `/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend` | layered `invite_mutation`, `invite_resend_invite`, `invite_resend_organisation_daily` |
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
| GET | `/api/v1/platform/staff/{staff_id}` | `platform_read` |
| POST | `/api/v1/platform/staff` | `platform_staff_write` |
| PATCH | `/api/v1/platform/staff/{staff_id}/role` | `platform_staff_write` |
| POST | `/api/v1/platform/staff/{staff_id}/suspend` | `platform_staff_write` |
| POST | `/api/v1/platform/staff/{staff_id}/restore` | `platform_staff_write` |
| GET | `/api/v1/platform/audit-events/limited` | `audit_read` |
| GET | `/api/v1/platform/audit-events` | `audit_read` |


## Invite layered anti-abuse model

Invite creation and resend use sequential multi-bucket Redis checks before the database session or invite services are constructed. These checks are intentionally part of the core rate-limit layer, not `InviteService`, so durable business rules remain separate from ephemeral anti-abuse controls.

Invite create (`POST /api/v1/organisations/{organisation_id}/invites`) checks, in order:

| Policy | Bucket kind | Default | Purpose |
| --- | --- | --- | --- |
| `invite_create` | `user` | 20 / hour | Limit one authenticated actor's invite creation rate. |
| `invite_create_organisation` | `organisation` | 50 / hour | Prevent multiple admins in the same organisation from multiplying spam. |
| `invite_create_organisation_daily` | `organisation` | 200 / day | Cap daily invite creation pressure from one organisation. |
| `invite_create_target_email` | `organisation_target_email` | 3 / day | Prevent repeated targeting of the same email address in one organisation. |
| `invite_create_target_domain` | `organisation_target_domain` | 50 / day | Prevent one organisation flooding one email domain. |

Invite resend (`POST /api/v1/organisations/{organisation_id}/invites/{invite_id}/resend`) checks, in order:

| Policy | Bucket kind | Default | Purpose |
| --- | --- | --- | --- |
| `invite_mutation` | `user` | 30 / hour | Limit one actor's invite administration mutation rate. |
| `invite_resend_invite` | `invite` | 5 / hour | Prevent repeatedly resending one invite. |
| `invite_resend_organisation_daily` | `organisation` | 200 / day | Prevent high-volume resend pressure from one organisation. |

Invite revoke keeps the existing `invite_mutation` actor bucket; no organisation-level revoke throttle is added at this stage.

Example policy override:

```bash
RATE_LIMITING__POLICIES__INVITE_CREATE_ORGANISATION_DAILY__LIMIT=100
RATE_LIMITING__POLICIES__INVITE_CREATE_ORGANISATION_DAILY__WINDOW_SECONDS=86400
RATE_LIMITING__POLICIES__INVITE_CREATE_TARGET_EMAIL__LIMIT=2
```

Daily windows use `86400` seconds and are supported by the policy registry. Existing `60`, `300`, and `3600` second windows remain supported.

### Privacy and identifier guarantees

All actor, IP, organisation, organisation+email, organisation+domain, and invite buckets use versioned HMAC-SHA256 bucket keys (`rlid:v1:hmac-sha256:<digest>`) with `RATE_LIMITING__IDENTIFIER_SECRET`. Redis namespaces include only the configured prefix, policy name, and bucket kind, for example `rate-limit:invite_create_target_email:organisation_target_email`.

Raw email addresses, email domains, organisation IDs, invite IDs, user IDs, IP addresses, tokens, token hashes, and encrypted raw tokens must not appear in Redis keys, namespaces, logs, metrics, audit metadata, or client errors. Metrics and logs may record low-cardinality `policy_name` and bucket/identifier kind only.

### Anti-abuse versus durable product limits

Redis-backed rate limits are ephemeral anti-abuse controls. They may expire, protect against spam/brute-force/floods/excessive retries, and return `429 Too Many Requests` with the standard Problem Details and `Retry-After` contract.

Durable product and subscription limits must remain database-backed and must not be implemented as Redis counters. Examples include plan seat limits, paid feature access, subscription entitlement, organisation capacity, and owner/admin invariants. Those future product contracts should return `403`, `402`, or `409` as appropriate, not `429`.

Sequential multi-bucket consumption is intentional conservative throttling: an earlier actor or organisation bucket may be consumed even if a later email/domain/invite bucket blocks the request. Lua scripts, custom Redis scripts, and atomic multi-key Redis transactions are intentionally out of scope for this stage.

## Identifier strategy

- Authenticated requests are bucketed by principal identity.
- Invite anti-abuse also uses custom business buckets for organisation, organisation+target-email, organisation+target-domain, and invite resend dimensions.
- Identifier kind is tracked via `rate_limit.identifier_kind` for observability.
- Redis bucket keys use versioned HMAC-SHA256 identifiers in the form `rlid:v1:hmac-sha256:<digest>`.
- HMAC messages use domain separation: `user:<external_auth_id>` for user buckets, `ip:<normalised_ip>` for IP buckets, and `<bucket_kind>:<raw_value>` for business buckets.
- Raw user ID/email/IP, organisation IDs, invite IDs, target emails, and target domains must not appear in Redis keys, logs, metrics, audit metadata, or client errors.
- IP addresses are normalised with the standard `ipaddress` canonical/compressed form.
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

Policy registry tests assert every named policy is registered and retrievable. Endpoint-protection tests introspect FastAPI route dependencies and verify sensitive route groups carry the expected endpoint-level policy metadata while health endpoints remain unprotected. Fake-limiter API tests cover `429` Problem Details, `Retry-After`, unauthenticated `401` before limiter checks, and blocking before service/DB execution for tenant write, audit read, and organisation create paths.

Platform write policies remain covered by both fast fake-limiter API regression tests and Redis/Testcontainers integration tests. The fake tests keep fail-closed and transaction-boundary behaviour cheap to validate, while the integration tests exercise `limits`, async Redis storage, real Redis windows, and real over-limit responses for `platform_write` and `platform_staff_write`.

## Testing commands

Run from `backend/`:

```bash
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
- [x] Invite create endpoint is layered by actor, organisation, target email, and target domain buckets.
- [x] Invite accept endpoint is rate limited.
- [x] Invite revoke remains actor rate limited and invite resend is layered by actor, invite, and organisation buckets.
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
