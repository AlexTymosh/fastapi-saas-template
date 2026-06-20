# Data Subject Request (DSR) workflow

## Current implemented scope

The current implementation provides a backend Data Subject Rights workflow for
the personal-data stores currently present in the SaaS template. Runtime erasure
coverage matches the declared privacy inventory through executable minimisation
providers plus explicit retain/manual-review policy entries.

Implemented areas:

- DSR persistence model, repository and service lifecycle.
- User-facing DSR submission, listing, read and cancellation API.
- Platform-facing DSR review, approval, rejection, cancellation and fulfilment
  API.
- Separate administrative lifecycle status and operational execution status.
- Idempotent DSR submission with hashed idempotency keys and safety validation.
- Platform permission boundaries for DSR read, review, export artifact metadata,
  export generation, export download URL generation and erase execution.
- Export artifact model, service, repository, user API, platform API and worker
  command.
- Multi-artifact export history per DSR, where the newest artifact is the source
  of truth for current export execution state.
- Dedicated export download URL rate limits, including an authorised
  artifact-scoped bucket after ownership/platform permission succeeds.
- S3-compatible export artifact storage for staging/production and local signed
  references for development/tests only.
- Cross-table subject export providers for the current privacy inventory scope.
- Erasure provider planning, preview, decision preservation and
  inventory-aligned coverage contracts.
- Executable erasure providers for audit, outbox, invites, platform staff,
  export-artifact metadata, privacy-governance source-field minimisation, DSR
  workflow metadata and user profile.
- Explicit retain/manual-review policy entries for membership, organisation and
  consent evidence records where automatic mutation would break tenant or
  compliance integrity.
- Platform erasure execution API for the current inventory-aligned workflow.
- Audit minimisation before destructive erasure providers run.
- Self-erasure execution rejection before provider orchestration.
- Automatic fulfilment after successful approved erase execution.
- Export artifact retention runner that removes expired archive objects from
  storage and clears storage metadata.
- Contract tests for privacy inventory, export provider keys, erasure coverage,
  provider decisions, rate-limit policy coverage and platform permissions.
- Opt-in MinIO/Testcontainers coverage for S3-compatible export storage.

Known erasure posture:

- Runtime erasure coverage matches the declared privacy inventory through a mix
  of executable minimisation providers and explicit retain/manual-review policy
  entries.
- Membership rows are retained by policy because deleting or re-parenting them
  would break tenant relationship integrity; direct identifiers are removed by
  the user-profile provider.
- Organisation rows are tenant-owned and retained with explicit manual-review
  policy for subject-related operational fields.
- Consent records are retained as compliance evidence while provider decisions
  remain visible to orchestration results.

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
- Download URL generation is rate-limited at actor and authorised artifact scope.

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
- `privacy_export_artifacts:read`
- `gdpr:export`
- `gdpr:erase`

Permission boundaries:

- `privacy_requests:read` allows platform DSR list/detail reads.
- `privacy_requests:review` allows platform review and decision transitions.
- `privacy_requests:execute_erasure` allows approved erase DSR execution.
- `privacy_export_artifacts:read` allows platform export artifact metadata
  list/detail reads.
- `gdpr:export` allows export artifact creation and download URL generation.
- `gdpr:erase` is the GDPR erase permission; erase execution is exposed through
  the dedicated `privacy_requests:execute_erasure` boundary.

Role posture:

- `platform_admin`: has the full permission set.
- `compliance_officer`: can read/review DSRs, read export artifact metadata,
  create/download export artifacts and execute approved erasure through the
  dedicated erase execution boundary.
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
- One export DSR can have multiple historical export artifacts; current DSR
  export execution state follows the newest artifact.
- Local storage is for development and tests only.
- Staging/production require S3-compatible object storage when privacy exports
  are enabled.
- Ready artifacts remain downloadable after export DSR fulfilment until expiry.
- S3-compatible downloads use short-lived presigned GET URLs.
- Local download references use signed `local://privacy-export/...` values and
  must not be treated as production HTTP download URLs.
- Download URL generation uses a dedicated privacy export download URL policy
  and an authorised artifact-scoped bucket.
- Audit metadata is minimised and does not include export payloads, signed URLs,
  storage keys, local paths or processing tokens.

## Erasure workflow

Approved erase DSRs execute through the platform erasure API and the internal
command-layer boundary.

Current executable/policy behaviour:

- The platform API requires `privacy_requests:execute_erasure`.
- The service maps execution and orchestration errors to application errors.
- The command layer locks and authorises the executor before execution.
- Self-erasure execution is rejected before provider orchestration.
- Providers run in this safe order:
  - audit minimisation;
  - outbox payload scrubbing;
  - invite anonymisation/minimisation;
  - membership retain-by-policy evidence;
  - organisation manual-review policy evidence;
  - platform staff minimisation;
  - export-artifact metadata minimisation;
  - privacy-governance authorisation minimisation;
  - privacy-governance consent retention-by-policy evidence;
  - privacy-governance notice acceptance minimisation;
  - user profile anonymisation;
  - DSR workflow metadata minimisation.
- Provider results preserve decisions such as `minimised`, `already_minimised`,
  `retained_by_policy` and `manual_review_policy`.
- Successful erasure writes execution audit evidence and automatically fulfils
  the DSR.
- Failed provider execution records failed execution state and does not fulfil
  the DSR.

Current erasure coverage:

- Membership subject links are retained by explicit policy while the linked user
  profile is anonymised.
- Organisation subject references are handled through explicit tenant-owned
  manual-review policy.
- Platform staff creator links and free-text suspension context are minimised
  where nullable.
- DSR workflow links, notes and idempotency metadata are minimised after the
  execution result has snapshotted the subject id.
- Export-artifact subject/actor links, worker lease metadata and failure details
  are minimised; binary object deletion remains governed by export-artifact
  retention.
- Privacy-governance source fields are minimised while lawful-basis, consent and
  notice evidence is retained.

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

## Issue #328 closure posture

The backend now satisfies the current #328 backend scope through implemented DSR
models, self-service and platform APIs, export artifact generation/delivery,
retention, S3-compatible storage, inventory-aligned export coverage and
erasure coverage through executable providers plus explicit policy decisions.

Issue #328 may be closed after this documentation reconciliation PR is merged
and the broad CI gate passes.

## Follow-up work

The following items remain intentionally separate from #328 closure:

- streaming archive generation for very large exports;
- PostgreSQL-specific JSON predicate export-provider tests;
- explicit export delivery evidence semantics;
- authorised representative workflows;
- frontend/UI;
- execution pipelines for rectify/restrict/object/access/portability request
  types.
