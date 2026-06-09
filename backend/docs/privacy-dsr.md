# Data Subject Request (DSR) workflow

## Current implemented scope

The current implementation provides a backend Data Subject Rights workflow for
large parts of the personal-data stores currently present in the SaaS template.
It should not yet be described as complete for erasure across every inventoried
store.

Implemented areas:

- DSR persistence model, repository and service lifecycle.
- User-facing DSR submission, listing, read and cancellation API.
- Platform-facing DSR review, approval, rejection, cancellation and fulfilment
  API.
- Separate administrative lifecycle status and operational execution status.
- Idempotent DSR submission with hashed idempotency keys and safety validation.
- Platform permission boundaries for DSR read, review, export and erase
  execution.
- Export artifact model, service, repository, user API, platform API and worker
  command.
- S3-compatible export artifact storage for staging/production.
- Cross-table subject export providers for the current privacy inventory scope.
- Erasure provider planning and preview.
- Executable erasure providers for audit, outbox, invites and user profile.
- Platform erasure execution API for the currently executable providers.
- Audit minimisation before destructive erasure providers run.
- Self-erasure execution rejection before provider orchestration.
- Automatic fulfilment after successful approved erase execution.
- Export artifact retention runner that removes expired archive objects from
  storage and clears storage metadata.
- Contract tests for privacy inventory, export provider keys and platform
  permissions.

Known erasure limitation:

- Executable erasure coverage does not yet match every erasure target declared in
  the privacy inventory.
- Membership, organisation, platform staff, DSR/export-artifact and
  privacy-governance subject references still need executable providers or
  explicit manual-review/retention rules before issue #328 can be closed.

## User API

Base path:

```text
/api/v1/privacy/data-subject-requests
```

Endpoints:

- `POST /` submit a self-service DSR.
- `GET /` list own DSR requests.
- `GET /{request_id}` read own DSR by id.
- `POST /{request_id}/cancel` cancel own request when lifecycle permits.

Export artifact endpoints:

```text
/api/v1/privacy/export-artifacts
```

Endpoints:

- `GET /` list own export artifacts.
- `GET /{artifact_id}` read own export artifact status and metadata.
- `POST /{artifact_id}/download-url` create a short-lived download URL for an
  own ready artifact.

Current user API constraints:

- Submission is self-service only: requester and subject are the same local user.
- Submitted request types may still require platform review and execution.
- Download URLs do not expose storage keys, local paths, processing tokens or raw
  payload internals.

## Platform API

Base path:

```text
/api/v1/platform/privacy/data-subject-requests
```

Endpoints:

- `GET /` list DSRs for review.
- `GET /{request_id}` read DSR.
- `POST /{request_id}/review` move submitted request to under review.
- `POST /{request_id}/approve` approve with optional structured reason code.
- `POST /{request_id}/reject` reject with required structured reason code.
- `POST /{request_id}/cancel` cancel when lifecycle permits.
- `POST /{request_id}/execute-erasure` execute an approved erase DSR.
- `POST /{request_id}/fulfil` fulfil an approved request when execution evidence
  exists.

Export artifact endpoints:

```text
/api/v1/platform/privacy
```

Endpoints:

- `POST /data-subject-requests/{request_id}/export-artifact` create a queued
  export artifact for an approved export DSR.
- `GET /export-artifacts` list export artifact metadata.
- `GET /export-artifacts/{artifact_id}` read export artifact metadata.
- `POST /export-artifacts/{artifact_id}/download-url` create a short-lived
  download URL for a ready artifact.

## Permissions

Platform permissions used by the DSR workflow:

- `privacy_requests:read`
- `privacy_requests:review`
- `privacy_requests:execute_erasure`
- `gdpr:export`
- `gdpr:erase`

Role posture:

- `platform_admin`: has the full permission set.
- `compliance_officer`: can read/review DSRs, create/download export artifacts,
  and execute approved erasure through the dedicated erase execution boundary.
- `support_agent`: denied by default for DSR read/review, export artifact and
  erasure execution operations.

## Lifecycle

Administrative DSR statuses:

- `submitted`
- `under_review`
- `approved`
- `rejected`
- `fulfilled`
- `cancelled`

Operational execution statuses:

- `not_started`
- `queued`
- `processing`
- `ready`
- `failed`
- `partially_fulfilled`
- `delivered`

Fulfilment rules:

- Export DSRs require at least one ready, non-expired export artifact before
  manual fulfilment.
- Successful approved erase execution automatically moves the DSR lifecycle to
  `fulfilled` for the current executable provider set.
- Failed erase execution keeps the DSR approved with failed execution state so a
  platform actor can investigate or retry.
- Non-implemented request execution types stay blocked from fulfilment until a
  concrete execution pipeline exists.

## Export workflow

Export artifacts are asynchronous and built from approved export DSRs only.

Current behaviour:

- Platform users with `gdpr:export` can create a queued export artifact.
- The worker command claims queued artifacts and generates a subject data ZIP.
- Export payloads are assembled from the current privacy inventory scope.
- Local storage is for development and tests only.
- Staging/production require S3-compatible object storage when privacy exports
  are enabled.
- Ready artifacts remain downloadable after export DSR fulfilment until expiry.
- S3-compatible downloads use short-lived presigned GET URLs.
- Audit metadata is minimised and does not include export payloads, signed URLs,
  storage keys, local paths or processing tokens.

## Erasure workflow

Approved erase DSRs execute through the platform erasure API and the internal
command-layer boundary.

Current executable behaviour:

- The platform API requires `privacy_requests:execute_erasure`.
- The service maps execution and orchestration errors to application errors.
- The command layer locks and authorises the executor before execution.
- Self-erasure execution is rejected before provider orchestration.
- Providers run in this safe order:
  - audit minimisation;
  - outbox payload scrubbing;
  - invite anonymisation/minimisation;
  - user profile anonymisation.
- Successful erasure writes execution audit evidence and automatically fulfils
  the DSR.
- Failed provider execution records failed execution state and does not fulfil
  the DSR.

Current erasure gaps:

- Membership subject links are not yet handled by executable erasure.
- Organisation subject references are not yet handled by executable erasure.
- Platform staff subject references are not yet handled by executable erasure.
- DSR/export-artifact subject references are not yet handled by executable
  erasure.
- Privacy-governance subject records are not yet handled by executable erasure.

## Retention

The privacy export retention runner processes expired ready export artifacts.

Command:

```text
python -m app.privacy.retention_cli
```

The runner:

- supports `--dry-run`;
- supports `--batch-size`;
- deletes the stored local/S3-compatible archive object;
- clears storage metadata on the artifact row;
- marks the artifact as `expired`;
- preserves delivered DSR execution state;
- marks undelivered expired export execution as failed with `artifact_expired`.

## Follow-up work

The #328 backend workflow is materially advanced but not yet closable because
executable erasure coverage does not match the declared inventory.

Closure blockers:

- executable erasure for memberships;
- executable erasure or manual-review policy for organisations;
- executable erasure or retention policy for platform staff links;
- safe handling for DSR/export-artifact links during erasure;
- safe handling for privacy-governance records during erasure.

Non-blocking hardening items:

- streaming archive generation for very large exports;
- PostgreSQL-specific integration tests for JSON predicate export paths;
- explicit delivery evidence beyond download URL/download count;
- authorised representative workflows;
- additional execution pipelines for rectification, restriction, objection,
  access and portability;
- frontend/UI.
