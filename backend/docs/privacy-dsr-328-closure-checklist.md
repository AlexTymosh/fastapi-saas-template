# Issue #328 closure readiness checklist

## Scope

This document maps the original issue #328 backend requirements to the current
implementation and the final closure posture.

The issue asked for a coordinated Data Subject Rights workflow that can respond
to subject requests and avoid manual database operations across current
personal-data stores.

## Current decision

Issue #328 is ready to close after this documentation reconciliation PR is
merged and the broad CI gate passes.

The backend now has a DSR foundation, export workflow, erase execution boundary,
expanded retention maintenance, operations visibility, explicit privacy
permissions, S3-compatible export storage, inventory-aligned export providers,
provider registry contracts, runtime/policy erasure coverage and documentation
contracts that keep the closure posture aligned.

The final required closure command is `task ci`.

## Current implemented erasure coverage

The current erasure orchestrator executes or records policy coverage for:

- `audit.minimise_subject_actor_or_target_identifiers`
- `outbox.purge_or_scrub_payload`
- `invites.anonymise_or_purge_subject_references`
- `memberships.minimise_subject_link`
- `organisations.review_subject_references`
- `platform_staff.minimise_subject_or_creator_links`
- `export_artifacts.delete_object_minimise_subject_or_actor_metadata`
- `privacy_governance.minimise_authorizations`
- `privacy_governance.minimise_consent_records`
- `privacy_governance.minimise_notice_acceptances`
- `users.anonymise_profile`
- `dsr.minimise_workflow_identifiers`

Membership, organisation and consent handling is intentionally policy-based
rather than fully destructive because those rows preserve tenant, access-control
or compliance integrity.

## Requirement mapping

Implemented for the current backend scope:

- Dedicated privacy/DSR module under `backend/app/privacy`.
- `DataSubjectRequest` model with request type, requester, subject, status,
  execution status, timestamps, reviewer and representative metadata.
- Platform DSR APIs protected by explicit privacy permissions.
- User self-service DSR APIs.
- Authorised representative DSR intake and platform authority review workflow.
- Representative fulfilment semantics for export ownership and erasure target
  selection.
- Export service through cross-table subject export providers.
- Export coverage for user profile, memberships, organisations, invites,
  outbox, audit, DSR/export metadata and privacy-governance records.
- Batched/keyset subject export provider iteration with deterministic ordering.
- Trim/lower normalisation for email-based invite helper subqueries used by
  export, outbox and audit lookup paths.
- Streaming export archive generation through temporary files instead of
  materialising the ZIP archive in memory.
- Export artifact delivery through queued artifacts, worker command, dedicated
  rate limits, short-lived URLs and explicit delivery confirmation endpoints.
- Production-grade export object storage option through S3-compatible storage
  with opt-in MinIO integration coverage.
- PostgreSQL/Testcontainers provider integration coverage for JSON predicates
  used by subject export, erasure impact preview and outbox erasure scrubbing.
- Privacy retention maintenance for export artifacts, invite lifecycle rows,
  delivered/failed outbox payloads, old audit context and expired DSR
  idempotency metadata.
- DSR operations visibility through read-only health snapshots, aggregate logs,
  low-cardinality metrics and `task privacy:dsr-health`.
- Erasure/anonymisation for the declared inventory through executable
  minimisation providers plus explicit retain/manual-review policies.
- User profile erasure.
- Invite erasure/minimisation.
- Outbox payload scrubbing.
- Audit record minimisation while retaining integrity.
- Membership erasure/minimisation through explicit retain-and-minimise policy;
  the linked user profile is anonymised.
- Organisation subject-reference handling through tenant-owned manual-review
  policy.
- Platform staff subject-reference handling for nullable creator links and
  free-text suspension context.
- DSR/export-artifact subject-reference handling for workflow and artifact
  metadata minimisation.
- Privacy-governance record handling through source-field minimisation plus
  retention of compliance evidence.
- Platform erasure execution API for the current executable/policy provider set.
- Self-erasure execution rejection.
- Self-erasure audit actor leakage guard.
- Successful erase fulfilment after inventory-aligned erasure execution.
- Legacy generic GDPR permission values removed from the runtime platform
  permission enum and current DSR/platform access docs.
- Contract tests proving inventory/export/erasure provider alignment.
- Contract tests proving erasure removes/minimises or policy-covers all
  inventoried personal-data stores through runtime and contract coverage tests.
- Contract tests proving current privacy docs do not retain stale #328 blockers.

## Closure blockers

No current implementation or documentation blocker remains for the backend #328
scope after this documentation reconciliation PR.

Final closure action:

- Priority: P1.
- Required command before closing: `task ci`.

## Post-#328 follow-up issues

These are separate from #328 closure blockers:

- Add frontend/UI for DSR workflows.
  - Priority: P2.
  - Rationale: current project scope is backend-only.
- Add storage-native delivery evidence ingestion, such as object-store access
  event processing.
  - Priority: P2.
  - Rationale: explicit user/platform delivery confirmation is implemented;
    storage-native evidence can extend it without blocking backend closure.
- Add execution pipelines for rectify/restrict/object/access/portability.
  - Priority: P2.
  - Rationale: these request types are accepted for review but blocked from
    approval until concrete execution policies exist.
- Add representative evidence document storage and UI review.
  - Priority: P2.
  - Rationale: backend authority metadata and review decisions are implemented;
    evidence-document handling is product and storage policy work.
- Add deployment manifests for production-specific runtime hardening.
  - Priority: P2.
  - Rationale: the backend image and runtime secret baseline exist; filesystem,
    capability and platform controls belong to deployment manifests.

## Verification commands

Recommended before closing #328:

```bash
task ci
```

Focused commands for this area when working from the backend directory:

```bash
uv run pytest tests/contracts/test_privacy_docs_contract.py
uv run pytest tests/privacy/test_privacy_provider_registry_alignment.py
uv run pytest tests/privacy/test_subject_data_exporter_batching.py
uv run pytest tests/privacy/test_subject_data_exporter_email_normalization.py
uv run pytest tests/privacy/test_privacy_dsr_execution_health.py
uv run pytest tests/privacy/test_privacy_retention_maintenance.py
uv run pytest tests/privacy/test_erasure_coverage_contract.py
uv run pytest tests/privacy/test_erasure_orchestrator.py
uv run pytest tests/privacy/test_erasure_execution.py
```

## Closure sign-off checklist

Before closing #328, confirm:

- [ ] This documentation reconciliation PR is merged.
- [ ] `task ci` passes on the branch that includes this PR.
- [ ] No new P0-P2 DSR/privacy regression was raised during review.
- [ ] Any future frontend, storage-native evidence or non-export execution work
      has a separate issue if the project owner wants it tracked.
