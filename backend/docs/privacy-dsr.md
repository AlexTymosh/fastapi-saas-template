# Data Subject Request Foundation (PR 1)

## Scope in this PR

This PR introduces the persistence and service foundation for a domain-neutral data-subject-request lifecycle.

Included:
- DSR model and migration;
- repository access layer;
- service-layer lifecycle/state transitions;
- due date calculation defaults;
- idempotency hash/fingerprint/TTL handling;
- compliance audit lifecycle events;
- service test coverage.

## Supported request types
- access
- export
- erase
- rectify
- restrict
- object
- portability

## Supported statuses
- submitted
- under_review
- approved
- rejected
- fulfilled
- cancelled

## SLA defaults
- `DEFAULT_DUE_DAYS = 30`
- `EXTENSION_DAYS = 60`
- `MAX_DUE_DAYS = 90`

The service calculates `due_at` at submit time.

## Idempotency behaviour
- `IDEMPOTENCY_KEY_TTL_HOURS = 24`
- raw idempotency key is not persisted;
- idempotency key validation runs before hashing;
- `idempotency_key_hash` and `idempotency_fingerprint` are persisted;
- same requester + same non-expired key + same fingerprint returns the existing request;
- same requester + same non-expired key + different fingerprint raises conflict;
- expired keys can be reused;
- idempotent submit serialises the requester row before the lookup/create path so concurrent same-requester retries cannot both miss the non-expired key in transactional databases that support row-level locks;
- PostgreSQL uses a `FOR NO KEY UPDATE` requester-row lock for this critical section, which avoids blocking foreign-key key-share checks that only need to verify the requester row still exists.

## Explicitly out of scope in this PR
- API routers and schemas;
- platform permissions and rate-limit policies for DSR endpoints;
- async export generation;
- signed download URLs;
- storage adapters;
- erasure/anonymisation execution;
- retention runners;
- document storage;
- authorised representative flows.

## PR 2 status update (API and access-control foundation)

Added in PR 2:
- user-facing API under `/api/v1/privacy/data-subject-requests`;
- platform-facing API under `/api/v1/platform/privacy/data-subject-requests`;
- platform permissions `privacy_requests:read` and `privacy_requests:review`;
- DSR submit rate limit policy `privacy_dsr_submit` (5/day, critical).

Current phase constraints:
- self-service only (`requester_user_id == subject_user_id`);
- no authorised representative flows;
- no asynchronous export generation;
- no signed download URLs;
- no erasure/anonymisation execution pipeline.
