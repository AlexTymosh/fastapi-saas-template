# Data Subject Request (DSR) Foundation

## Current implemented scope

Implemented across PR-1 and PR-2:
- DSR persistence model, migration, repository, and service lifecycle foundation;
- idempotent submission controls (hashed key, fingerprint, TTL window);
- due date defaults and lifecycle timestamps;
- compliance audit lifecycle events;
- user-facing and platform-facing DSR HTTP API;
- platform permissions and DSR submit rate limiting.

Implemented as export artifact foundation in PR-378:
- `ExportArtifact` model, migration, repository, service, schemas, and API foundation;
- asynchronous queued export artifact generation for approved export DSRs;
- worker-friendly command: `python -m app.commands.privacy_export_worker`;
- local development/test storage adapter;
- short-lived HMAC-signed local download URL/token support;
- user-facing export artifact list/read/download-url endpoints;
- platform-facing export artifact create/list/read/download-url endpoints;
- export artifact lifecycle audit events;
- privacy export settings and local signing-secret guardrails;
- service, repository, storage, API, worker, settings, and OpenAPI contract tests.

## User API

Base path: `/api/v1/privacy/data-subject-requests`

Endpoints:
- `POST /` submit DSR (self-service only);
- `GET /` list own DSR requests;
- `GET /{request_id}` read own DSR by id;
- `POST /{request_id}/cancel` cancel own request when lifecycle permits.

Export artifact endpoints:

Base path: `/api/v1/privacy/export-artifacts`

Endpoints:
- `GET /` list own export artifacts;
- `GET /{artifact_id}` read own export artifact status/metadata;
- `POST /{artifact_id}/download-url` create a short-lived download URL for own ready artifact.

Phase constraints:
- self-service DSR submission only (`requester_user_id == subject_user_id`);
- DSR submission payload accepts `request_type` only;
- no unrestricted requester free-text notes in PR-2;
- platform fulfilment is guarded: export requests require a ready, non-expired
  export artifact before they can be marked fulfilled;
- export artifact payload currently contains a minimal metadata-only JSON ZIP, not full cross-table subject data coverage.

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

Export artifact endpoints:

Base path: `/api/v1/platform/privacy`

Endpoints:
- `POST /data-subject-requests/{request_id}/export-artifact` create a queued export artifact for an approved export DSR;
- `GET /export-artifacts` list export artifact metadata;
- `GET /export-artifacts/{artifact_id}` read export artifact metadata;
- `POST /export-artifacts/{artifact_id}/download-url` create a short-lived download URL for a ready artifact.

## Permissions

Platform permissions:
- `privacy_requests:read`
- `privacy_requests:review`
- `gdpr:export`

Role posture:
- `platform_admin`: allowed through full permission set;
- `compliance_officer`: allowed DSR read/review and export artifact creation/download through `gdpr:export`;
- `support_agent`: denied by default for DSR read/review and export artifact operations.

## Rate limits

- User submit path uses `privacy_dsr_submit` policy:
  - limit: 5
  - window: 86400 seconds
  - fail-open: false
  - sensitivity: critical
- DSR read and export artifact read paths use existing authenticated read policy patterns.
- Platform mutation paths use existing platform write policy pattern.

## Idempotency

Submission supports `Idempotency-Key` header.
- Same requester + same key + same payload -> existing request is returned.
- Same requester + same key + different payload -> conflict.

## Lifecycle

Supported DSR statuses:
- submitted
- under_review
- approved
- rejected
- fulfilled
- cancelled

Supported export artifact statuses:
- queued
- processing
- ready
- failed
- expired
- cancelled

Current platform fulfil flow allows fulfilment only for approved DSRs and now
requires execution evidence before final fulfilment:
- export DSRs require at least one ready, non-expired export artifact;
- erasure, rectification, restriction, objection, access, and portability DSRs
  are blocked from fulfilment until their execution pipelines exist.

A later execution-architecture slice should still introduce first-class worker
execution records, retry state, partial fulfilment, and delivery evidence.
Ready, non-expired export artifacts remain downloadable after their parent
export DSR moves from `approved` to `fulfilled`; fulfilment records that the
artifact is ready, not that the requester has already downloaded it.

## Export artifacts

Export artifacts are asynchronous and built from approved export DSRs only.

Current behaviour:
- platform users with `gdpr:export` can create a queued export artifact for an approved export DSR;
- the worker command claims queued artifacts and generates a minimal JSON ZIP archive;
- local storage is intended for development and tests only;
- ready artifacts remain downloadable after export DSR fulfilment until expiry;
- local download URLs are short-lived and HMAC-signed;
- API responses do not expose storage keys, local filesystem paths, processing tokens, or raw export payloads;
- audit metadata is minimised and does not include export payloads, signed URLs, or storage paths.

## Explicitly out of scope

Not implemented in this phase:
- full cross-table personal-data export coverage across users, memberships, organisations, invites, outbox, audit, and future product records;
- streaming export provider contracts and memory-safe export writer;
- production object storage / S3-compatible storage adapter;
- production HTTP/S3 download flow;
- erasure/anonymisation execution;
- retention purge runner that deletes expired objects from storage;
- full DSR worker execution state machine with retry/partial-failure handling;
- authorised representative flows;
- PDF/CSV export formats;
- frontend/UI.
