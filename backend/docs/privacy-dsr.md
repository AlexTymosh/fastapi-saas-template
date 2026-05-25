# Data Subject Request (DSR) Foundation

## Current implemented scope

Implemented across PR-1 and PR-2:
- DSR persistence model, migration, repository, and service lifecycle foundation;
- idempotent submission controls (hashed key, fingerprint, TTL window);
- due date defaults and lifecycle timestamps;
- compliance audit lifecycle events;
- user-facing and platform-facing DSR HTTP API;
- platform permissions and DSR submit rate limiting.

## User API

Base path: `/api/v1/privacy/data-subject-requests`

Endpoints:
- `POST /` submit DSR (self-service only);
- `GET /` list own DSR requests;
- `GET /{request_id}` read own DSR by id;
- `POST /{request_id}/cancel` cancel own request when lifecycle permits.

Phase constraints:
- self-service only (`requester_user_id == subject_user_id`);
- API payload accepts `request_type` only;
- no unrestricted requester free-text notes in PR-2.

## Platform API

Base path: `/api/v1/platform/privacy/data-subject-requests`

Endpoints:
- `GET /` list DSRs for review;
- `GET /{request_id}` read DSR;
- `POST /{request_id}/review` submitted -> under_review;
- `POST /{request_id}/approve` approve with optional structured reason code;
- `POST /{request_id}/reject` reject with required structured reason code;
- `POST /{request_id}/cancel` cancel when lifecycle permits;
- `POST /{request_id}/fulfil` fulfil approved request.

## Permissions

Platform permissions:
- `privacy_requests:read`
- `privacy_requests:review`

Role posture:
- `platform_admin`: allowed through full permission set;
- `compliance_officer`: allowed read/review;
- `support_agent`: denied by default for DSR read/review.

## Rate limits

- User submit path uses `privacy_dsr_submit` policy:
  - limit: 5
  - window: 86400 seconds
  - fail-open: false
  - sensitivity: critical
- Platform mutation paths use existing platform write policy pattern.

## Idempotency

Submission supports `Idempotency-Key` header.
- Same requester + same key + same payload -> existing request is returned.
- Same requester + same key + different payload -> conflict.

## Lifecycle

Supported statuses:
- submitted
- under_review
- approved
- rejected
- fulfilled
- cancelled

Public platform fulfil flow in PR-2 allows fulfilment only for approved requests.

## Explicitly out of scope

Not implemented in this phase:
- async export generation;
- signed download URLs;
- storage adapters and document storage;
- export artifact pipeline;
- erasure/anonymisation execution;
- retention runners;
- authorised representative flows;
- frontend/UI.
