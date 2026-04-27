# Rate Limiting

## Current phase

- Rate limiting is implemented with Redis-backed storage through the `limits` library.
- Rate limiting is disabled by default.
- Redis is required only when `RATE_LIMITING__ENABLED=true`.
- Rate limiting is currently applied to selected sensitive flows.
- Health endpoints are not rate limited.

## Configuration

| Setting | Purpose | Notes |
|---|---|---|
| `RATE_LIMITING__ENABLED` | Enables rate-limiting runtime | Default is disabled |
| `RATE_LIMITING__BACKEND` | Selects storage backend | Redis-backed configuration is used in current phase |
| `RATE_LIMITING__REDIS_PREFIX` | Namespaces limiter keys in Redis | Keep stable across app instances for shared enforcement |
| `RATE_LIMITING__TRUST_PROXY_HEADERS` | Controls whether proxy headers are used for client identity derivation | Default is `false` |
| `RATE_LIMITING__DEFAULT_LIMIT` | Default request limit for policies using defaults | Applies when policy-level values are not overridden |
| `RATE_LIMITING__DEFAULT_WINDOW_SECONDS` | Default time window for default policy limits | Applies when policy-level values are not overridden |
| `RATE_LIMITING__DEFAULT_FAIL_OPEN` | Default backend failure behavior for non-sensitive policies | Use with caution |
| `RATE_LIMITING__SENSITIVE_FAIL_OPEN` | Backend failure behavior for sensitive policies | Sensitive flows should remain fail-closed |
| `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS` | Timeout for storage operations | Limits backend wait time during checks |
| `REDIS__URL` | Redis connection URL | Required only when rate limiting is enabled |

Safe defaults:

- Rate limiting is disabled by default.
- `RATE_LIMITING__TRUST_PROXY_HEADERS=false` by default.
- Redis URL is required only when rate limiting is enabled.

## Policies

| Policy | Limit | Window | Fail mode | Purpose |
|---|---:|---:|---|---|
| `invite_accept` | 5 | 5 minutes | fail-closed | Protect invite token acceptance |
| `invite_create` | 20 | 1 hour | fail-closed | Protect invite creation abuse |

## Policy registry

- Policies are registered in the rate-limit policy registry.
- Duplicate policy names are rejected.
- Unknown policy names raise a clear error.
- The policy registry is intentionally static in the current phase.

## Identifier strategy

- Authenticated users are rate-limited independently.
- The limiter uses a low-cardinality identifier kind such as `user`.
- Raw user IDs, emails, tokens, request IDs, trace IDs, and IPs must not be used as metric labels.
- Identifier values must not be exposed in logs or metrics.

## Proxy headers

- `RATE_LIMITING__TRUST_PROXY_HEADERS=false` by default.
- Do not enable trusted proxy headers unless the app is behind a trusted reverse proxy.
- Never trust `X-Forwarded-For` directly from the public internet.
- Incorrect proxy configuration can cause unrelated users to share a bucket or allow spoofing.

## Failure modes

### Redis/backend unavailable

- Sensitive policies fail closed.
- API returns `503` Problem Details.
- Metric outcome: `backend_error`.
- Backend error metric is recorded.

### Fail-open policy

- If a policy is configured fail-open and backend fails, request is allowed.
- Metric outcome: `fail_open`.
- This should be treated as degraded mode.

### Runtime unavailable

- Rate limiting is enabled, but limiter runtime or limiter instance is missing.
- API returns `503` Problem Details.
- Metric outcome: `runtime_unavailable`.
- This indicates an application lifecycle/configuration problem.

### Over limit

- API returns `429` Problem Details.
- `Retry-After` header is returned.
- Metric outcome: `blocked`.

## HTTP contract

- Over-limit responses return `429`.
- Backend unavailable responses return `503`.
- Unauthenticated protected requests return `401` before rate limiter execution.
- Rate limiter must not execute endpoint body or DB I/O when request is blocked.
- Response schemas and Problem Details contracts must remain stable.

## Observability

Current rate-limit metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Allowed `rate_limit.result` values:

- `allowed`
- `blocked`
- `backend_error`
- `fail_open`
- `runtime_unavailable`

Allowed metric attributes:

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

## Operational risks

- Shared NAT/shared IP bucket issues when identity derivation is misconfigured.
- Reverse proxy misconfiguration causing incorrect client attribution.
- Redis outage impacting backend checks.
- Rate limiter runtime not initialized while feature is enabled.
- Accidentally enabling fail-open for sensitive flows.
- High-cardinality metrics if raw identifiers are exposed.

## Testing expectations

Expected coverage:

- Disabled rate limiting is a no-op.
- Enabled rate limiting requires Redis URL in real lifecycle.
- Over-limit returns `429`.
- Backend failure with fail-closed policy returns `503`.
- Fail-open allows request and records degraded outcome.
- Unauthenticated request returns `401` before limiter.
- Endpoint body and DB I/O are not executed on `429`.
- Runtime unavailable returns `503` and records `runtime_unavailable`.

## Future improvements

- Optional OTel Collector profile for local verification.
- Dashboards and alert rules.
- Policy metadata when more policies are added.
- Policy inventory tests for protected endpoints.
- Production proxy-header deployment guidance.
