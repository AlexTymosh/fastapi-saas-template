# Data Subject Request (DSR) workflow

## Current implemented scope

The current implementation provides a backend Data Subject Rights workflow for
the personal-data stores currently present in the SaaS template. Runtime erasure
coverage matches the declared privacy inventory through executable minimisation
providers plus explicit retain/manual-review policy entries.

Implemented areas:

- DSR persistence model, repository and service lifecycle.
- User-facing DSR submission, listing, read and cancellation API.
- Authorised representative DSR intake and verification metadata, with approval
  blocked unless platform review verifies authority.
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
- `requester_role` defaults to `self`. In this mode the subject is inferred
  from the authenticated user and representative fields are rejected.
- `requester_role=authorised_representative` requires `subject_user_id`,
  `representative_relationship` and `representative_authority_note`. These
  requests are stored with `representative_status=pending_verification` and
  cannot be approved until platform verification marks authority as `verified`.
  Self-service idempotent retries accept the pre-representative fingerprint format
  for rows that are still inside the 24-hour idempotency-key TTL window.

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

- Submission defaults to self-service: requester and subject are the same
  local user unless the requester explicitly declares an authorised
  representative flow.
- Representative submissions are intake-only in this PR slice. They are visible
  to platform reviewers but blocked from approval while their authority remains
  `pending_verification` or `rejected`.
- Request types without an implemented execution policy may be submitted for
  platform review, but they cannot be approved until a concrete policy exists.
- Requester notes are stored for platform review but are not returned in
  user-facing DSR responses.
- Download URLs do not expose storage keys, local paths, processing tokens or raw
  payload internals.
- Download URL creation records URL issuance only. It does not mark the export
  DSR as delivered until delivery is explicitly confirmed.
- Download URL generation and delivery confirmation are rate-limited at actor and
  authorised artifact scope.

## Authorised representative intake

This backend slice supports intake guardrails for DSRs submitted by an
authorised representative. The requester can identify another local user as the
subject only when `requester_role=authorised_representative` is declared and
relationship plus authority details are provided.

Representative verification endpoints let platform reviewers mark authority
as `verified` or `rejected`. Approval remains blocked while authority is
`pending_verification` or `rejected`. The verification endpoints store only
structured status/reason metadata and rely on audit events for the reviewing
actor, rather than storing copies of evidence documents.

Verifier-only links are treated as first-class workflow references. Subject data
exports include DSR rows where the exporting subject is only
`representative_verified_by_user_id` as reference records, while requester,
subject and unrelated reviewer identifiers stay minimised. Erasure impact
previews use the same verifier predicate as the DSR workflow erasure provider so
platform reviewers see the same row count that execution will minimise.

Represented subject existence checks are routed through `UserRepository` before
DSR insert, so the service layer does not own SQL for the users aggregate.
Representative verification and rejection writes are conditional on the current
DSR lifecycle status and representative authority status. Stale concurrent
updates return a conflict and do not emit representative authority audit events.

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
- `POST /{request_id}/representative/verify` mark representative authority
  verified with optional structured reason code.
- `POST /{request_id}/representative/reject` mark representative authority
  rejected with required structured reason code.
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
- Download URL generation and delivery confirmation use a dedicated privacy
  export download URL policy and an authorised artifact-scoped bucket.
- Delivery confirmation performs an atomic final eligibility check against the
  linked DSR before writing confirmed-delivery evidence.
- Audit metadata is minimised and does not include export payloads, signed URLs,
  storage keys, local paths or processing tokens.

## Erasure workflow

Approved erase DSRs execute through the platform erasure API and the internal
command-layer boundary.

### Export URL issuance migration

Legacy export rows created before explicit delivery confirmation used download
metadata as URL issuance metadata. The delivery-evidence migration reclassifies
those values into URL issuance columns and clears confirmed-delivery columns.
After the migration, `delivered` execution state is reserved for explicit
confirmation evidence only.

During the PR #428 migration, legacy URL-issued export DSR rows are
reclassified from their latest export artifact. Ready legacy artifacts remain
ready for confirmation, while expired legacy artifacts become failed with
`artifact_expired` evidence.

### Export delivery evidence migration guardrails

The export delivery evidence migration reclassifies legacy URL-issued export DSRs
from the latest artifact state. Latest ready artifacts return to `ready`, latest
expired artifacts become `artifact_expired` failures, and latest cancelled
artifacts become failed delivery evidence using the cancellation reason. This
prevents legacy URL issuance from remaining visible as confirmed delivery.
