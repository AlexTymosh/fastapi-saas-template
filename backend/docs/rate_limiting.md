# Rate limiting

## Current phase

Rate limiting is implemented for selected sensitive endpoints using Redis-backed `limits`.

## Default behaviour

- disabled by default;
- `RATE_LIMITING__ENABLED=false`;
- Redis is required only when rate limiting is enabled;
- startup fails fast if rate limiting is enabled and `REDIS__URL` is missing.

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
- 429 responses include `Retry-After`;
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

## Acceptance checklist

- [ ] default local/test startup does not require Redis;
- [ ] rate limiting enabled without Redis fails fast;
- [ ] invite create is rate limited;
- [ ] invite accept is rate limited;
- [ ] 401 happens before limiter for unauthenticated protected requests;
- [ ] 429 includes Problem Details;
- [ ] 429 includes `Retry-After`;
- [ ] 429 does not execute endpoint body;
- [ ] 429 does not perform DB I/O;
- [ ] fail-closed backend error returns 503;
- [ ] rate-limit metrics are recorded;
- [ ] sensitive endpoint protection is enforced by tests.
