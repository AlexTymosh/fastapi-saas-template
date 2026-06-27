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
- Optional requester details for self-service submissions, stored for platform
  review without echoing the note in user-facing DSR responses.
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

Submission payload:

- `request_type` is required.
- `requester_note` is optional, trimmed at the API boundary and limited to 2000
  characters. Blank notes are stored as `null`.

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
- Request types without an implemented execution policy may be submitted for
  platform review, but they cannot be approved until a concrete policy exists.
- Requester notes are stored for platform review but are not returned in
  user-facing DSR responses.
- Download URLs do not expose storage keys, local paths, processing tokens or raw
  payload internals.
- Download URL creation records URL issuance only. It does not mark the export
  DSR as delivered until delivery is explicitly confirmed.
- Download URL generation is rate-limited at actor and authorised artifact scope.

## Request-type execution policy

The backend currently has executable fulfilment policies for:

- `export`
- `erase`

The following request types are accepted into the review lifecycle only:

- `access`
- `rectify`
- `restrict`
- `object`
- `portability`

Review-only request types can be reviewed, rejected or cancelled. They cannot be
approved or fulfilled until the project defines a concrete execution policy for
that request type. The approval guard is enforced in the central service
transition path, so internal callers cannot bypass the policy by calling
`transition_status(...APPROVED...)` directly. This prevents
approved-but-unfulfillable DSR rows while still preserving visibility of
submitted rights requests for platform review.

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

Platform DSR responses include `requester_note` so authorised reviewers can see
requester-provided details. Audit metadata must stay minimal and must not copy
full requester notes.

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
- `POST /export-artifacts/{artifact_id}/confirm-delivery` confirm export
  delivery evidence for an artifact.
- `POST /{artifact_id}/confirm-delivery` confirm that the requester received
  the export artifact.

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
- Review-only request types stay blocked from approval and fulfilment until a
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
- URL issuance is tracked separately from delivery evidence; confirmed
  delivery is recorded only through the delivery confirmation endpoint.
- Local download references use signed `local://privacy-export/...` values and
  must not be treated as production HTTP download URLs.
- Download URL generation uses a dedicated privacy export download URL policy
  and an authorised artifact-scoped bucket.
- Audit metadata is minimised and does not include export payloads, signed URLs,
  storage keys, local paths or processing tokens.

## Erasure workflow

Approved erase DSRs execute through the platform erasure API and the internal
command-layer boundary.
