# Rate limiting

## Current phase

Rate limiting is implemented for selected sensitive endpoints using Redis-backed `limits`.

## Baseline behavior

- `RATE_LIMITING__ENABLED=false` by default for easy local startup.
- Redis is required only when `RATE_LIMITING__ENABLED=true`.
- Startup fails fast if rate limiting is enabled and `REDIS__URL` is missing.

## Production/staging security behavior

In secure environments (`APP__ENVIRONMENT=staging` or `prod`):

- `RATE_LIMITING__ENABLED=false` fails startup by default.
- Emergency bypass requires explicit `RATE_LIMITING__ALLOW_DISABLED_IN_PROD=true`.
- Bypass usage logs a high-severity security warning event: `rate_limiting_disabled_in_secure_environment`.

This enforces explicit, auditable intent and prevents silent insecure deployment.

## Policies

| Policy | Limit | Window | fail_open | Purpose |
|---|---:|---|---|---|
| invite_create | 20 | 1 hour | false | Prevent invite creation abuse |
| invite_accept | 5 | 5 minutes | false | Reduce invite token brute-force risk |

## Protected endpoint matrix

| Method | Endpoint | Policy |
|---|---|---|
| POST | `/api/v1/organisations/{organisation_id}/invites` | `invite_create` |
| POST | `/api/v1/invites/accept` | `invite_accept` |

## Explicit default policy factory (no automatic fallback)

The project provides default policy settings:

- `RATE_LIMITING__DEFAULT_LIMIT`
- `RATE_LIMITING__DEFAULT_WINDOW_SECONDS`
- `RATE_LIMITING__DEFAULT_FAIL_OPEN`

These values are used only by an explicit default policy factory (`name="default"`).

Important:

- No automatic fallback exists.
- Unknown policy names still raise an error.
- Endpoint authors must explicitly attach the default policy when needed.

Example usage pattern:

```python
default_policy = build_explicit_default_policy(settings.rate_limiting)
Depends(rate_limit_dependency(default_policy))
```

## Contracts

- unauthenticated protected requests return 401 before rate-limit checks;
- authenticated over-limit requests return 429;
- 429 responses include Problem Details + `Retry-After`;
- Redis/rate-limiter backend failure under fail-closed policy returns 503;
- over-limit requests must not execute endpoint body;
- over-limit requests must not perform DB I/O.

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
