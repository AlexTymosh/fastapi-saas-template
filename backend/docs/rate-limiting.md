# Rate limiting

## Current status

Rate limiting is implemented with `limits` using an async Redis backend.

The project has two complementary layers:

1. **Ingress pre-auth layer** — `RateLimitIngressMiddleware` protects protected
   API traffic before JWT validation.
2. **Endpoint/business layer** — route dependencies protect authenticated
   endpoint groups and business-specific abuse dimensions.

Default local/test enablement remains disabled:

```bash
RATE_LIMITING__ENABLED=false
```

Staging and production are stricter:

- staging/prod require either app-level rate limiting or verified edge
  enforcement;
- app-level rate limiting in staging/prod requires pre-auth protection unless
  verified edge mode is configured;
- app-level pre-auth protection in staging/prod requires trusted proxy headers
  and trusted proxy CIDRs unless verified edge mode is configured;
- verified edge mode requires trusted proxy CIDRs and an edge assertion
  header/secret.

Health endpoints are excluded from app-level pre-auth throttling and the
edge-assertion hard gate.

## Configuration

Primary settings:

| Setting | Purpose |
|---|---|
| `RATE_LIMITING__ENABLED` | Enables app-level Redis-backed rate limiting. |
| `RATE_LIMITING__BACKEND` | Rate-limit backend. Currently `redis`. |
| `RATE_LIMITING__REDIS_PREFIX` | Redis namespace prefix for rate-limit buckets. |
| `RATE_LIMITING__TRUST_PROXY_HEADERS` | Allows forwarded client IP headers only when the immediate peer is trusted. |
| `RATE_LIMITING__TRUSTED_PROXY_CIDRS` | CIDRs allowed to provide forwarded client IP headers. |
| `RATE_LIMITING__PRE_AUTH_ENABLED` | Enables ingress pre-auth throttling for protected API paths. |
| `RATE_LIMITING__IDENTIFIER_SECRET` | HMAC secret for bucket identifiers. |
| `RATE_LIMITING__ENFORCED_BY_EDGE` | Allows app-level limiting to be disabled only when trusted edge enforcement is verified. |
| `RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME` | Header used by the trusted edge/gateway. |
| `RATE_LIMITING__EDGE_ASSERTION_SECRET` | Shared assertion secret used to validate edge-originated requests. |
| `RATE_LIMITING__MODE` | `normal`, `strict`, `relaxed`, or `panic`. |
| `RATE_LIMITING__POLICIES__<POLICY_NAME>__LIMIT` | Optional per-policy limit override. |
| `RATE_LIMITING__POLICIES__<POLICY_NAME>__WINDOW_SECONDS` | Optional per-policy window override. |
| `RATE_LIMITING__POLICIES__<POLICY_NAME>__FAIL_OPEN` | Optional per-policy fail-open override. |
| `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS` | Timeout for Redis limiter operations. |
| `REDIS__URL` | Required when app-level rate limiting is enabled. |

Rules:

- `REDIS__URL` is required when `RATE_LIMITING__ENABLED=true`.
- `RATE_LIMITING__IDENTIFIER_SECRET` is required when app-level limiting is
  enabled.
- identifier and edge assertion secrets must be at least 32 characters.
- trusted proxy headers require trusted proxy CIDRs in staging/prod.
- staging/prod require app-level limiting or verified edge enforcement.
- unknown policy override names fail fast.
- invalid override limits/windows fail fast.
- `relaxed` mode is rejected in production.

Generate a strong identifier secret with OpenSSL:

```bash
openssl rand -hex 32
```

Do not commit real secrets.

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

### Verified edge protection

Use this only when a trusted edge/API gateway/WAF enforces rate limits before
traffic reaches the application origin:

```bash
RATE_LIMITING__ENABLED=false
RATE_LIMITING__ENFORCED_BY_EDGE=true
RATE_LIMITING__TRUSTED_PROXY_CIDRS=10.0.0.0/8
RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME=X-Edge-Assertion
RATE_LIMITING__EDGE_ASSERTION_SECRET=<strong-shared-secret>
```

In verified edge mode:

- the immediate peer must be in `RATE_LIMITING__TRUSTED_PROXY_CIDRS`;
- the configured assertion header must be present;
- the assertion value must match `RATE_LIMITING__EDGE_ASSERTION_SECRET`;
- direct-origin requests are rejected with `403`;
- health probes remain excluded from the hard gate.

## Policy resolution

Policy defaults are declared in `backend/app/core/rate_limit/policies.py`.

Precedence:

1. policy spec defaults;
2. mode transformation;
3. explicit per-policy override.

In `panic` mode, sensitive and critical policies remain fail-closed even if an
override attempts `FAIL_OPEN=true`.

## Policy matrix

| Policy | Default limit | Default window | Default fail mode | Sensitivity | Purpose |
|---|---:|---|---|---|---|
| `pre_auth` | 120 | 1 minute | fail-open | sensitive | Pre-auth IP/client protection for protected API paths before JWT validation. |
| `authenticated_default` | 120 | 1 minute | fail-open | normal | Low-risk authenticated reads such as `/users/me`. |
| `tenant_read` | 120 | 1 minute | fail-open | normal | Tenant read, directory, and membership listing endpoints. |
| `tenant_write` | 30 | 1 minute | fail-closed | sensitive | Tenant mutations and membership management. |
| `tenant_write_organisation` | 60 | 1 minute | fail-closed | sensitive | Organisation-scoped tenant write operations. |
| `organisation_create` | 5 | 1 hour | fail-closed | critical | Protect organisation creation/onboarding from abuse. |
| `invite_accept` | 5 | 5 minutes | fail-closed | critical | Protect invite acceptance from brute force/token guessing. |
| `invite_accept_token` | 5 | 5 minutes | fail-closed | critical | Protect invite-token specific acceptance checks. |
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
| `privacy_dsr_submit` | 5 | 1 day | fail-closed | critical | Protect DSR submit/cancel flows from abuse. |
| `privacy_export_download_url` | 10 | 5 minutes | fail-closed | critical | Protect export artifact download URL generation. |

Fail-open is reserved for low-risk availability paths. Sensitive endpoint and
business policies remain fail-closed.

## Authenticated and business rate-limit layer

Endpoint-level dependencies run after authentication and before endpoint
body/database work for protected routes.

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
| POST | `/api/v1/invites/accept` | `invite_accept` / `invite_accept_token` |
| DELETE | `/api/v1/organisations/{organisation_id}/invites/{invite_id}` | `invite_mutation` |
| POST | `/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend` | layered `invite_mutation`, `invite_resend_invite`, `invite_resend_organisation_daily` |
| POST | `/api/v1/privacy/data-subject-requests` | `privacy_dsr_submit` |
| POST | `/api/v1/privacy/data-subject-requests/{request_id}/cancel` | `privacy_dsr_submit` |
| POST | `/api/v1/privacy/export-artifacts/{artifact_id}/download-url` | authorised artifact-scoped `privacy_export_download_url` |
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
| GET | `/api/v1/platform/privacy/data-subject-requests` | `platform_read` |
| GET | `/api/v1/platform/privacy/data-subject-requests/{request_id}` | `platform_read` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/review` | `platform_write` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/approve` | `platform_write` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/reject` | `platform_write` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/cancel` | `platform_write` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure` | `platform_write` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/fulfil` | `platform_write` |
| POST | `/api/v1/platform/privacy/data-subject-requests/{request_id}/export-artifact` | `platform_write` |
| GET | `/api/v1/platform/privacy/export-artifacts` | `platform_read` |
| GET | `/api/v1/platform/privacy/export-artifacts/{artifact_id}` | `platform_read` |
| POST | `/api/v1/platform/privacy/export-artifacts/{artifact_id}/download-url` | authorised artifact-scoped `privacy_export_download_url` |

## Invite layered anti-abuse model

Invite create and resend endpoints use two layers of protection:

1. **Actor-level endpoint dependency** — limits the authenticated actor.
2. **Authorised business-scope buckets** — run only after tenant
   membership/role checks and non-mutating preconditions pass.

Authorised business-scope invite buckets are consumed through
`check_rate_limits_for_buckets()`. Redis-backed runtime uses a static Lua script
with all-or-nothing semantics.

## Platform privacy rate-limit model

Platform privacy endpoints use the same layered model as the rest of the
platform API:

- platform privacy list/detail reads use `platform_read`;
- DSR review, approval, rejection, cancellation, erasure execution, fulfilment,
  and export-artifact creation use `platform_write` through the rate-limited
  platform write context;
- export-artifact metadata list/detail reads use `platform_read`;
- export download URL generation uses `privacy_export_download_url`, followed by
  an authorised artifact-scoped bucket after platform permission succeeds.

This keeps operator-facing documentation aligned with route dependencies and
prevents future drift from hiding unlisted platform privacy endpoints.

## Privacy DSR/export anti-abuse model

DSR submission and cancellation use the `privacy_dsr_submit` critical policy.

Export artifact download URL generation uses the
`privacy_export_download_url` critical policy after the caller is authorised for
the artifact. This prevents unauthorised users from consuming another subject's
artifact-scoped bucket.

Download URL responses must not expose storage keys, local paths, processing
tokens, raw payload data, or unsigned object identifiers.

## Identifier strategy

- Authenticated requests are bucketed by principal identity.
- Pre-auth requests are bucketed by normalised client IP.
- Invite anti-abuse uses custom business buckets for organisation, target email,
  target domain, and invite resend dimensions.
- Privacy export download URL generation uses an authorised artifact-scoped
  bucket.
- Redis bucket keys use versioned HMAC-SHA256 identifiers.
- Raw user ID/email/IP, organisation IDs, invite IDs, artifact IDs, target
  emails, and target domains must not appear in Redis keys, logs, metrics, audit
  metadata, or client errors.
- Forwarded client IP headers are ignored unless the immediate peer is inside
  `RATE_LIMITING__TRUSTED_PROXY_CIDRS`.

## Proxy and edge trust model

Keep `RATE_LIMITING__TRUST_PROXY_HEADERS=false` unless the proxy chain is
explicitly trusted.

When proxy headers are enabled:

- the app first checks the immediate peer IP;
- `X-Forwarded-For` / `X-Real-IP` are used only if the peer is inside
  `RATE_LIMITING__TRUSTED_PROXY_CIDRS`;
- spoofed forwarded headers from direct clients are ignored.

## Redis outage behaviour

Runtime/backend failures follow policy fail mode.

- **Fail-closed** (`fail_open=false`): return `503`
  (`error_code=rate_limiter_unavailable`).
- **Fail-open** (`fail_open=true`): allow request, emit a backend-error metric,
  and log a security warning.
- **Runtime unavailable**: return `503`
  (`error_code=rate_limiter_unavailable`).

## Retry-After contract

Over-limit responses must:

- return `429`;
- use Problem Details with `application/problem+json`;
- include `Retry-After`;
- include `Access-Control-Expose-Headers: Retry-After`;
- use policy-expiry fallback if Redis window stats are unavailable.

## Metrics contract

Metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Allowed attributes:

- `rate_limit.policy`
- `rate_limit.result`
- `rate_limit.identifier_kind`
- `error.type`

Forbidden high-cardinality/sensitive values:

- raw user id/email/IP;
- organisation id;
- invite id;
- artifact id;
- request id/trace id;
- raw path/URL;
- token;
- Redis key;
- identifier raw/hashed value.

## Testing coverage

Policy registry tests assert every named policy is registered and retrievable.

Endpoint-protection tests introspect FastAPI route dependencies and verify
sensitive route groups carry the expected endpoint-level policy metadata while
health endpoints remain unprotected by endpoint dependencies.

Fake-limiter API tests cover:

- `429` Problem Details;
- `Retry-After`;
- pre-auth `429` before JWT validation;
- missing token consuming the pre-auth bucket and then returning `401`;
- valid authenticated requests still using the post-auth user bucket;
- health endpoint bypasses;
- blocking before service/DB execution for sensitive paths;
- fail-closed and fail-open Redis/backend behaviour;
- platform privacy read/write route-limit documentation coverage;
- privacy DSR submission/cancellation throttling;
- export download URL throttling after authorisation.

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
```

Full project validation:

```bash
task ci
```

## Acceptance checklist

- [x] Default local/test startup does not require Redis.
- [x] Enabling app-level rate limiting without Redis fails fast.
- [x] Staging/prod require either app-level rate limiting or verified edge
      enforcement.
- [x] App-level rate limiting in staging/prod requires pre-auth protection unless
      verified edge mode is configured.
- [x] Edge-enforced mode requires trusted proxy CIDRs and an assertion
      header/secret.
- [x] Forwarded client IP headers are accepted only from trusted proxy CIDRs.
- [x] Pre-auth throttling can block missing/invalid-token traffic before JWT
      validation.
- [x] Invite create endpoint is layered by actor, organisation, target email, and
      target domain buckets.
- [x] Invite accept endpoint is rate limited.
- [x] Invite revoke remains actor rate limited and invite resend is layered by
      actor, invite, and organisation buckets.
- [x] Authenticated `/users/me` is rate limited.
- [x] Tenant read/write/create endpoint groups are rate limited.
- [x] Platform read/list/detail endpoint groups are rate limited.
- [x] Platform full and limited audit listing endpoints are rate limited.
- [x] Platform privacy DSR read/write endpoints are documented in the protected
      endpoint matrix.
- [x] Platform privacy export-artifact read/write/download endpoints are
      documented in the protected endpoint matrix.
- [x] DSR submit/cancel endpoints are rate limited.
- [x] User and platform export artifact download URL generation is rate limited
      after ownership/platform permission succeeds.
- [x] Health endpoints are excluded from pre-auth throttling and edge-assertion
      hard deny, including trailing-slash variants.
- [x] `429` includes Problem Details payload.
- [x] `429` includes `Retry-After`.
- [x] Over-limit requests do not execute endpoint body.
- [x] Over-limit requests do not perform DB I/O for newly covered sensitive
      paths.
- [x] Fail-closed backend outage returns `503` Problem Details.
- [x] Observability uses low-cardinality policy/result/identifier-kind/error-type
      labels only.
