# Rate Limiting

## Current phase

Rate limiting is implemented through Redis and the `limits` library.

Current implementation status:

- rate limiting is disabled by default;
- Redis is required only when `RATE_LIMITING__ENABLED=true`;
- rate limiting is currently enabled only for selected sensitive flows;
- health endpoints are not rate limited.

## Configuration

Current configuration settings:

- `RATE_LIMITING__ENABLED`
- `RATE_LIMITING__BACKEND`
- `RATE_LIMITING__REDIS_PREFIX`
- `RATE_LIMITING__TRUST_PROXY_HEADERS`
- `RATE_LIMITING__DEFAULT_LIMIT`
- `RATE_LIMITING__DEFAULT_WINDOW_SECONDS`
- `RATE_LIMITING__DEFAULT_FAIL_OPEN`
- `RATE_LIMITING__SENSITIVE_FAIL_OPEN`
- `RATE_LIMITING__STORAGE_TIMEOUT_SECONDS`
- `REDIS__URL`

Safe defaults:

- rate limiting is disabled by default;
- `RATE_LIMITING__TRUST_PROXY_HEADERS=false` by default;
- `REDIS__URL` is required only when rate limiting is enabled.

## Policies

| Policy | Limit | Window | Fail mode | Purpose |
|---|---:|---:|---|---|
| `invite_accept` | 5 | 5 minutes | fail-closed | Protect invite token acceptance |
| `invite_create` | 20 | 1 hour | fail-closed | Protect invite creation abuse |

## Policy registry

- policies are registered in the rate-limit policy registry;
- duplicate policy names are rejected;
- unknown policy names raise a clear error;
- the policy registry is intentionally static for now.

## Identifier strategy

- authenticated users are rate-limited independently;
- the limiter uses a low-cardinality identifier kind such as `user`;
- raw user IDs, emails, tokens, request IDs, trace IDs, and IPs must not be used as metric labels;
- identifier values must not be exposed in logs or metrics.

## Proxy headers

- `RATE_LIMITING__TRUST_PROXY_HEADERS=false` by default;
- do not enable trusted proxy headers unless the app is behind a trusted reverse proxy;
- never trust `X-Forwarded-For` directly from the public internet;
- incorrect proxy configuration can cause unrelated users to share a bucket or allow spoofing.

## Failure modes

### Redis/backend unavailable

- sensitive policies fail closed;
- API returns 503 Problem Details;
- metric outcome: `backend_error`;
- backend error metric is recorded.

### Fail-open policy

- if a policy is configured fail-open and backend fails, request is allowed;
- metric outcome: `fail_open`;
- this should be treated as degraded mode.

### Runtime unavailable

- rate limiting is enabled, but limiter runtime or limiter instance is missing;
- API returns 503 Problem Details;
- metric outcome: `runtime_unavailable`;
- this indicates an application lifecycle/configuration problem.

### Over limit

- API returns 429 Problem Details;
- `Retry-After` header is returned;
- metric outcome: `blocked`.

## HTTP contract

- over limit returns 429;
- backend unavailable returns 503;
- unauthenticated protected request returns 401 before rate limiter;
- rate limiter must not execute endpoint body or DB I/O when request is blocked;
- response schemas and Problem Details contract must remain stable.

## Observability

Current rate-limit metric names:

- `rate_limit.requests.total`
- `rate_limit.backend_errors.total`
- `rate_limit.check.duration`

Allowed results:

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

- shared NAT or shared IP bucket effects;
- reverse proxy misconfiguration;
- Redis outage;
- rate limiter runtime not initialized;
- accidentally enabling fail-open for sensitive flows;
- high-cardinality metrics if raw identifiers are exposed.

## Testing expectations

- disabled rate limiting is a no-op;
- enabled rate limiting requires Redis URL in real lifecycle;
- over-limit returns 429;
- backend failure fail-closed returns 503;
- fail-open allows request but records degraded outcome;
- unauthenticated request returns 401 before limiter;
- endpoint body and DB I/O are not executed on 429;
- runtime unavailable returns 503 and records `runtime_unavailable`.

## Future improvements

- optional OTel Collector profile;
- dashboards and alert rules;
- policy metadata when more policies are added;
- policy inventory tests for protected endpoints;
- production proxy-header deployment guidance.
