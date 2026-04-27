# Rate limiting

## Current phase

Rate limiting is implemented for selected sensitive endpoints using Redis-backed `limits`.

## Default behavior

- disabled by default (`RATE_LIMITING__ENABLED=false`);
- Redis is required only when rate limiting is enabled;
- startup fails fast when rate limiting is enabled and `REDIS__URL` is missing.

## Security behavior for staging/prod

In secure environments (`APP__ENVIRONMENT=staging|prod`):

- `RATE_LIMITING__ENABLED=false` + `RATE_LIMITING__ALLOW_DISABLED_IN_PROD=false` => startup fail-fast.
- `RATE_LIMITING__ENABLED=false` + `RATE_LIMITING__ALLOW_DISABLED_IN_PROD=true` => startup allowed with explicit security warning log.

`RATE_LIMITING__ALLOW_DISABLED_IN_PROD=true` is an emergency bypass and must be explicit and auditable.

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

## Contracts

- unauthenticated protected requests return 401 before rate-limit checks;
- authenticated over-limit requests return 429;
- 429 responses use Problem Details and include `Retry-After`;
- Redis/rate-limiter backend failure under fail-closed policy returns 503;
- over-limit requests must not execute endpoint body;
- over-limit requests must not perform DB I/O.

## Explicit default policy factory (no fallback)

The following settings are used only for creating an explicit default policy object:

- `RATE_LIMITING__DEFAULT_LIMIT`
- `RATE_LIMITING__DEFAULT_WINDOW_SECONDS`
- `RATE_LIMITING__DEFAULT_FAIL_OPEN`

Important:

- there is no automatic policy fallback;
- unknown policy names must fail clearly;
- endpoint authors must explicitly attach a policy.

Example (explicit usage):

```python
default_policy = create_explicit_default_policy(settings.rate_limiting)
Depends(rate_limit_dependency(default_policy))
```

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
