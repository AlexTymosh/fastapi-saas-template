# Rate limiting

## Current status

Rate limiting is implemented with `limits` using an async Redis backend.

The project now has two complementary rate-limit layers:

1. **Ingress pre-auth layer** — `RateLimitIngressMiddleware` protects protected API traffic before JWT validation. It throttles missing, malformed, or invalid-token traffic before it reaches authentication and database-dependent dependencies.
2. **Endpoint/business layer** — route dependencies protect authenticated endpoint groups and business-specific abuse dimensions such as tenant writes, organisation creation, invite creation, invite resend, platform reads/writes, and audit reads.

Default local/test enablement remains disabled:

```bash
RATE_LIMITING__ENABLED=false
```

Staging and production are stricter:

- staging/prod require either app-level rate limiting or verified edge enforcement;
- app-level rate limiting in staging/prod requires pre-auth protection unless verified edge mode is configured;
- app-level pre-auth protection in staging/prod requires trusted proxy headers and trusted proxy CIDRs unless verified edge mode is configured;
- verified edge mode requires trusted proxy CIDRs and an edge assertion header/secret.

Health endpoints are excluded from app-level pre-auth throttling and the edge-assertion hard gate.

## Configuration

Primary settings:

| Setting | Purpose |
|---|---|
| `RATE_LIMITING__ENABLED` | Enables app-level Redis-backed rate limiting. |
| `RATE_LIMITING__BACKEND` | Rate-limit backend. Currently `redis`. |
| `RATE_LIMITING__REDIS_PREFIX` | Redis namespace prefix for rate-limit buckets. |
| `RATE_LIMITING__TRUST_PROXY_HEADERS` | Allows forwarded client IP headers only when the immediate peer is trusted. |
| `RATE_LIMITING__TRUSTED_PROXY_CIDRS` | Comma-separated CIDRs for reverse proxies/load balancers allowed to provide `X-Forwarded-For` / `X-Real-IP`. |
| `RATE_LIMITING__PRE_AUTH_ENABLED` | Enables ingress pre-auth IP/client throttling for protected API paths. |
| `RATE_LIMITING__IDENTIFIER_SECRET` | HMAC secret for rate-limit bucket identifiers. Required when app-level rate limiting is enabled. |
| `RATE_LIMITING__ENFORCED_BY_EDGE` | Allows app-level rate limiting to be disabled only when trusted edge enforcement is verified. |
| `RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME` | Header name used by the trusted edge/gateway to assert that the request passed edge enforcement. |
| `RATE_LIMITING__EDGE_ASSERTION_SECRET` | Shared assertion secret used to validate edge-originated requests. |
| `RATE_LIMITING__MODE` | `normal`, `strict`, `relaxed`, or `panic`. `relaxed` is rejected in production. |
| `RATE_LIMITING__POLICIES__<POLICY_NAME>__LIMIT` | Optional per-policy limit override. |
| `RATE_LIMITING__POLICIES__<POLICY_NAME>__WINDOW_SECONDS` | Optional per-policy window override. Supported windows: `60`, `300`, `3600`, `86400`. |
| `RATE_LIMITING__POLICIES__<POLICY_NAME>__FAIL_OPEN` | Optional per-policy fail-open override. Rejected for sensitive/critical policies in staging/prod. |
| `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS` | Timeout for Redis limiter operations. |
| `REDIS__URL` | Required when app-level rate limiting is enabled. |

Rules:

- `REDIS__URL` is required when `RATE_LIMITING__ENABLED=true`.
- `RATE_LIMITING__IDENTIFIER_SECRET` is required when `RATE_LIMITING__ENABLED=true`.
- `RATE_LIMITING__IDENTIFIER_SECRET` and `RATE_LIMITING__EDGE_ASSERTION_SECRET` must be at least 32 characters.
- `RATE_LIMITING__TRUST_PROXY_HEADERS=true` requires `RATE_LIMITING__TRUSTED_PROXY_CIDRS` in staging/prod.
- In staging/prod, either `RATE_LIMITING__ENABLED=true` or `RATE_LIMITING__ENFORCED_BY_EDGE=true` is required.
- In staging/prod, `RATE_LIMITING__ENABLED=true` requires `RATE_LIMITING__PRE_AUTH_ENABLED=true` unless verified edge mode is enabled.
- In staging/prod, app-level pre-auth without verified edge mode requires `RATE_LIMITING__TRUST_PROXY_HEADERS=true` and `RATE_LIMITING__TRUSTED_PROXY_CIDRS`, so pre-auth buckets use the real client IP instead of a shared ingress/load-balancer IP.
- `RATE_LIMITING__ENFORCED_BY_EDGE=true` requires `RATE_LIMITING__TRUSTED_PROXY_CIDRS`, `RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME`, and `RATE_LIMITING__EDGE_ASSERTION_SECRET`.
- Unknown policy override names fail fast.
- Invalid override limits/windows fail fast.
- `relaxed` mode is rejected in production.
- `panic` mode is accepted in production and is config-level only; there is no runtime/admin UI panic switch.

Generate a strong identifier secret with OpenSSL:

```bash
openssl rand -hex 32
```

Do not commit real secrets. Staging and production should inject secrets through the deployment platform, Vault, or another secret manager.

Rotating `RATE_LIMITING__IDENTIFIER_SECRET` changes HMAC bucket keys and resets active limiter buckets. This is acceptable for rate limiting, but rotation is best done during a low-traffic window or as part of compromise response. No dual-read/dual-write rotation is implemented.

## Production and staging protection modes

### App-level protection

Use this when the application itself owns Redis-backed throttling:

```bash
RATE_LIMITING__ENABLED=true
RATE_LIMITING__PRE_AUTH_ENABLED=true
RATE_LIMITING__IDENTIFIER_SECRET=<strong-secret>
REDIS__URL=redis://redis:6379/0
RATE_LIMITING__TRUST_PROXY_HEADERS=true
RATE_LIMITING__TRUSTED_PROXY_CIDRS=10.0.0.0/8
RATE_LIMITING__ENFORCED_BY_EDGE=false
```

In this mode:

- `RateLimitIngressMiddleware` applies the `pre_auth` policy before JWT validation for protected API paths;
- endpoint-level dependencies still apply authenticated/business-specific policies after authentication;
- missing/invalid token traffic can return `429` before `401` if the pre-auth bucket is exhausted;
- in staging/prod, forwarded client IP headers must be trusted only from configured proxy CIDRs to avoid collapsing all users behind one ingress IP into one bucket.

### Verified edge protection

Use this only when a trusted edge/API gateway/WAF enforces rate limits before traffic reaches the application origin:

```bash
RATE_LIMITING__ENABLED=false
RATE_LIMITING__ENFORCED_BY_EDGE=true
RATE_LIMITING__TRUSTED_PROXY_CIDRS=10.0.0.0/8
RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME=X-Edge-Assertion
RATE_LIMITING__EDGE_ASSERTION_SECRET=<strong-shared-secret>
```

In this mode:

- the immediate peer must be in `RATE_LIMITING__TRUSTED_PROXY_CIDRS`;
- the configured assertion header must be present;
- the assertion value must match `RATE_LIMITING__EDGE_ASSERTION_SECRET`;
- direct-origin requests are rejected with `403`;
- health probes under `/api/v1/health/live` and `/api/v1/health/ready` are excluded from the edge-assertion hard gate, including trailing-slash variants.

The current edge assertion model is a shared secret header. Timestamped/HMAC-signed edge assertions are not implemented in this PR and should be handled as a separate hardening task if required.

## Policy resolution

Policy defaults are declared in `backend/app/core/rate_limit/policies.py` as declarative specs. Startup resolves effective runtime policies from those specs, selected mode, and explicit per-policy overrides.

Precedence:

1. policy spec defaults;
2. mode transformation;
3. explicit per-policy override.

Exception: in `panic` mode, sensitive and critical policies always remain fail-closed even if an override attempts `FAIL_OPEN=true`.

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
| `pre_auth` | 120 | 1 minute | fail-open | sensitive | Pre-auth IP/client protection for protected API paths before JWT validation. |
| `authenticated_default` | 120 | 1 minute | fail-open | normal | Low-risk authenticated reads such as `/users/me`. |
| `tenant_read` | 120 | 1 minute | fail-open | normal | Tenant read, directory, and membership listing endpoints. |
| `tenant_write` | 30 | 1 minute | fail-closed | sensitive | Tenant mutations and membership management. |
| `organisation_create` | 5 | 1 hour | fail-closed | critical | Protect organisation creation/onboarding from abuse. |
| `invite_accept` | 5 | 5 minutes | fail-closed | critical | Protect invite acceptance from brute force/token guessing. |
| `invite_create` | 20 | 1 hour | fail-closed | sensitive | Protect invite creation by authenticated actor. |
| `invite_create_organisation` | 50 | 1 hour | fail-closed | sensitive | Limit organisation-wide invite creation bursts. |
| `invite_create_organisation_daily` | 200 | 1 day | fail-closed | critical | Cap daily organisation-wide invite creation pressure. |
| `invite_create_target_email` | 3 | 1 day | fail-closed | critical | Limit repeated invite creation to one email within one organisation. |
| `invite_create_target_domain` | 50 | 1 day | fail-closed | sensitive | Limit invite creation to one target domain within one organisation. |
| `invite_mutation` | 30 | 1 hour | fail-closed | sensitive | Protect invite revoke/resend/admin invite operations. |
| `invite_resend_invite` | 5 | 1 hour | fail-closed | sensitive | Limit repeated resend attempts for one invite. |
| `invite_resend_organisation_daily` | 200 | 1 day | fail-closed | sensitive | Cap daily organisation-wide resend pressure. |
| `platform_read` | 60 | 1 minute | fail-closed | sensitive | Reduce platform user/organisation/staff enumeration and listing abuse. |
| `audit_read` | 30 | 1 minute | fail-closed | critical | Protect sensitive full and limited audit listing/filtering. |
| `platform_write` | 30 | 1 minute | fail-closed | critical | Protect sensitive platform user/organisation writes. |
| `platform_staff_write` | 10 | 1 minute | fail-closed | critical | Protect high-impact platform staff management writes. |

Fail-open is reserved for low-risk availability paths. The `pre_auth` policy also fails open for Redis/backend errors so that the ingress layer does not turn low-risk read endpoints such as `authenticated_default` and `tenant_read` into fail-closed endpoints before their route-specific policies can run. Sensitive endpoint/business policies such as tenant writes, organisation creation, invite administration, audit reads, and platform writes remain fail-closed at the endpoint/business layer.

## Ingress pre-auth layer

`RateLimitIngressMiddleware` runs before route dependencies. It is responsible for controls that must happen before authentication:

- verified edge assertion checks;
- pre-auth IP/client throttling.

The pre-auth limiter applies only when:

- `RATE_LIMITING__ENABLED=true`;
- `RATE_LIMITING__PRE_AUTH_ENABLED=true`;
- the request path starts with the configured API prefix, normally `/api/v1/`;
- the method is not `OPTIONS`;
- the endpoint is not an excluded health endpoint.

Excluded by default from pre-auth throttling and edge-assertion hard deny:

- `/api/v1/health/live`;
- `/api/v1/health/live/`;
- `/api/v1/health/ready`;
- `/api/v1/health/ready/`.

Important behaviour change:

- unauthenticated protected requests are no longer guaranteed to return `401` before any limiter check;
- if the pre-auth bucket is over limit, the request can return `429` before JWT validation;
- if the pre-auth bucket allows the request, normal authentication still returns `401` for missing/invalid credentials.

## Authenticated and business rate-limit layer

Endpoint-level dependencies still own authenticated and business-specific policies. These checks run after authentication and before endpoint body/database work for protected routes.

Protected endpoint matrix:

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

Invite create and resend endpoints use two layers of protection:

1. **Actor-level endpoint dependency** — runs early after authentication and before endpoint body work where possible. It limits the authenticated actor (`invite_create` or `invite_mutation`).
2. **Authorised business-scope buckets** — run later in `InviteService`, only after tenant membership/role checks and other non-mutating preconditions pass. This prevents cross-tenant quota poisoning by authenticated outsiders.

Authorised business-scope invite buckets are consumed through `check_rate_limits_for_buckets()`. In Redis-backed runtime this uses a static Lua script with all-or-nothing semantics: every grouped business bucket is checked first, and no bucket is incremented unless all grouped buckets can be consumed. Non-Redis runtimes and lightweight test doubles keep the compatibility fallback path.

Invite create (`POST /api/v1/organisations/{organisation_id}/invites`) uses:

| Layer | Policy | Bucket kind | Default | Purpose |
|---|---|---|---|---|
| Endpoint actor | `invite_create` | `user` | 20 / hour | Limit one authenticated actor's invite creation rate. |
| Authorised grouped business | `invite_create_organisation` | `organisation` | 50 / hour | Prevent multiple admins in the same organisation from multiplying spam. |
| Authorised grouped business | `invite_create_organisation_daily` | `organisation` | 200 / day | Cap daily invite creation pressure from one organisation. |
| Authorised grouped business | `invite_create_target_email` | `organisation_target_email` | 3 / day | Prevent repeated targeting of the same email address in one organisation. |
| Authorised grouped business | `invite_create_target_domain` | `organisation_target_domain` | 50 / day | Prevent one organisation flooding one email domain. |

Invite resend (`POST /api/v1/organisations/{organisation_id}/invites/{invite_id}/resend`) uses:

| Layer | Policy | Bucket kind | Default | Purpose |
|---|---|---|---|---|
| Endpoint actor | `invite_mutation` | `user` | 30 / hour | Limit one actor's invite administration mutation rate. |
| Authorised grouped business | `invite_resend_invite` | `invite` | 5 / hour | Prevent repeatedly resending one invite. |
| Authorised grouped business | `invite_resend_organisation_daily` | `organisation` | 200 / day | Prevent high-volume resend pressure from one organisation. |

Invite revoke keeps the existing `invite_mutation` actor bucket; no organisation-level revoke throttle is added at this stage.

## Identifier strategy

- Authenticated requests are bucketed by principal identity.
- Pre-auth requests are bucketed by normalised client IP.
- Invite anti-abuse also uses custom business buckets for organisation, organisation+target-email, organisation+target-domain, and invite resend dimensions.
- Identifier kind is tracked via `rate_limit.identifier_kind` for observability.
- Redis bucket keys use versioned HMAC-SHA256 identifiers in the form `rlid:v1:hmac-sha256:<digest>`.
- HMAC messages use domain separation: `user:<external_auth_id>` for user buckets, `ip:<normalised_ip>` for IP buckets, and `<bucket_kind>:<raw_value>` for business buckets.
- Raw user ID/email/IP, organisation IDs, invite IDs, target emails, and target domains must not appear in Redis keys, logs, metrics, audit metadata, or client errors.
- IPv4 addresses are canonicalised.
- IPv6 addresses are normalised to a `/64` network address to reduce bypass risk from IPv6 address rotation.
- Forwarded client IP headers are ignored unless the immediate peer is inside `RATE_LIMITING__TRUSTED_PROXY_CIDRS`.

## Proxy and edge trust model

Keep `RATE_LIMITING__TRUST_PROXY_HEADERS=false` unless the proxy chain is explicitly trusted.

When proxy headers are enabled:

- the app first checks the immediate peer IP;
- `X-Forwarded-For` / `X-Real-IP` are used only if the peer is inside `RATE_LIMITING__TRUSTED_PROXY_CIDRS`;
- spoofed forwarded headers from direct clients are ignored.

When edge-enforced mode is enabled:

- the same trusted proxy check applies;
- the configured assertion header must be present;
- the assertion value must match the configured secret;
- otherwise protected API requests are rejected with `403`;
- health endpoints are excluded from the hard deny so liveness/readiness probes can still reach the app origin.

## Redis outage behaviour

Runtime/backend failures follow policy fail mode.

- **Fail-closed** (`fail_open=false`): return `503` (`error_code=rate_limiter_unavailable`). Sensitive tenant writes, organisation create, invite administration, audit/platform reads, and platform writes block when Redis/rate-limiter is unavailable.
- **Fail-open** (`fail_open=true`): allow request, emit backend-error metric, log security warning. This applies to low-risk authenticated reads, tenant reads, and the ingress `pre_auth` policy so Redis backend errors do not bypass route-specific fail-closed policies or turn fail-open read routes into fail-closed routes before authentication.
- **Runtime unavailable** (limiter/runtime missing): return `503` (`error_code=rate_limiter_unavailable`).

In all backend failure paths, observability metrics are emitted.

## Grouped business bucket atomicity

Grouped business bucket checks use a Redis Lua script with all-or-nothing semantics in one round-trip for Redis-backed execution:

- all grouped bucket keys are checked first;
- if any bucket is already at/over limit, no grouped bucket is incremented;
- grouped increments happen only when every bucket can be consumed.

This closes concurrent TOCTOU preflight/hit races for grouped business checks.

Implementation notes:

- Keys are passed via Lua `KEYS`; limits and window metadata are passed via `ARGV`.
- The script is static and parameterised (no per-request Lua source generation).
- Grouped Redis keys are prefixed with the shared `{rl-grouped-v1}` hash tag so all keys touched by one grouped Lua invocation are mapped to the same Redis Cluster hash slot while still keeping HMAC bucket identifiers as the only per-subject key material.
- The grouped atomic path uses simple Redis counters plus TTL, so its grouped semantics are fixed-window style even when the single-bucket limiter strategy is moving-window or sliding-window.
- A compatibility fallback path remains for non-Redis runtimes and lightweight test doubles.
- If Redis Cluster still returns a CROSSSLOT/same-slot script error, the request falls back to the compatibility `test()` + `hit()` path instead of turning fail-closed invite create/resend checks into rate-limiter-unavailable responses.
- Redis script/backend errors, including script response errors, are routed through the strictest grouped policy's fail-open/fail-closed setting.
- A blocked bucket without TTL is repaired defensively by setting its expected expiry before returning `Retry-After`.

Redis Cluster caveat:

- Grouped Lua evaluation requires all grouped keys to be in the same Redis hash slot.
- The default grouped key builder uses a shared hash tag for this purpose.
- This keeps grouped Lua atomicity available in Redis Cluster, but concentrates grouped limiter keys into one hash slot. For higher-volume clustered deployments, introduce a deliberate hash-tag sharding strategy and prove that every logical grouped bucket still uses one stable Redis key.
- The CROSSSLOT fallback preserves availability and previous behaviour, but it is not atomic and should be treated as degraded mode.

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

## Testing coverage

Policy registry tests assert every named policy is registered and retrievable. Endpoint-protection tests introspect FastAPI route dependencies and verify sensitive route groups carry the expected endpoint-level policy metadata while health endpoints remain unprotected by endpoint dependencies.

Fake-limiter API tests cover:

- `429` Problem Details;
- `Retry-After`;
- pre-auth `429` before JWT validation;
- missing token consuming the pre-auth bucket and then returning `401`;
- valid authenticated requests still using the post-auth user bucket;
- runtime settings coming from `request.app.state.settings` when `create_app(settings=...)` is used;
- health endpoint exact and trailing-slash paths bypassing pre-auth throttling and edge-assertion hard deny;
- blocking before service/DB execution for sensitive paths;
- fail-closed and fail-open Redis/backend behaviour.

Settings tests cover:

- trusted proxy CIDR parsing and validation;
- RFC token validation for edge assertion header names;
- staging/prod requiring app-level or verified edge protection;
- staging/prod rejecting app-level rate limiting without pre-auth unless verified edge mode is configured;
- staging/prod requiring trusted proxy client IP mode for app-level pre-auth without verified edge enforcement;
- staging/prod validating edge-enforced mode controls;
- production transport security guardrails.

## Testing commands

Run from `backend/`:

```bash
uv run --locked pytest -q tests/config/test_rate_limit_ingress_settings.py
uv run --locked pytest -q tests/rate_limit/test_identifiers.py
uv run --locked pytest -q tests/rate_limit/test_ingress_rate_limiting.py
uv run --locked pytest -q tests/rate_limit/test_api_rate_limiting.py
uv run --locked pytest -q tests/rate_limit/test_policy_registry.py
uv run --locked pytest -q tests/rate_limit/test_endpoint_protection.py
uv run --locked pytest -q tests/platform/test_platform_write_rate_limiting.py
uv run --locked pytest -q tests/platform/test_platform_write_rate_limiting_integration.py -m integration -rs
uv run --locked pytest -q tests/api/test_rate_limiting_integration.py -m integration -rs
uv run --locked pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```

Full project validation:

```bash
task ci
```

## Acceptance checklist

- [x] Default local/test startup does not require Redis.
- [x] Enabling app-level rate limiting without Redis fails fast.
- [x] Staging/prod require either app-level rate limiting or verified edge enforcement.
- [x] App-level rate limiting in staging/prod requires pre-auth protection unless verified edge mode is configured.
- [x] App-level pre-auth in staging/prod requires trusted proxy client IP mode unless verified edge mode is configured.
- [x] Edge-enforced mode requires trusted proxy CIDRs and an assertion header/secret.
- [x] Edge assertion header names are restricted to valid HTTP token characters.
- [x] Forwarded client IP headers are accepted only from trusted proxy CIDRs.
- [x] Pre-auth throttling can block missing/invalid-token traffic before JWT validation.
- [x] Missing-token traffic consumes the pre-auth bucket and then returns `401` when allowed.
- [x] Valid authenticated requests still use post-auth user/business buckets.
- [x] `create_app(settings=...)` is respected by runtime limiter checks.
- [x] Invite create endpoint is layered by actor, organisation, target email, and target domain buckets.
- [x] Invite accept endpoint is rate limited.
- [x] Invite revoke remains actor rate limited and invite resend is layered by actor, invite, and organisation buckets.
- [x] Authenticated `/users/me` is rate limited.
- [x] Tenant read/write/create endpoint groups are rate limited.
- [x] Platform read/list/detail endpoint groups are rate limited.
- [x] Platform full and limited audit listing endpoints are rate limited.
- [x] Health endpoints are excluded from pre-auth throttling and edge-assertion hard deny, including trailing-slash variants.
- [x] `429` includes Problem Details payload.
- [x] `429` includes `Retry-After`.
- [x] Over-limit requests do not execute endpoint body.
- [x] Over-limit requests do not perform DB I/O for newly covered sensitive paths.
- [x] Fail-closed backend outage returns `503` Problem Details.
- [x] Observability uses low-cardinality policy/result/identifier-kind/error-type labels only.
