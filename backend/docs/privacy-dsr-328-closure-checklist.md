# Issue #328 closure readiness checklist

## Scope

This document maps the original issue #328 requirements to the current backend
implementation and the final closure posture.

The issue asked for a coordinated Data Subject Rights workflow that can respond
to subject requests and avoid manual database operations across current
personal-data stores.

## Current decision

Issue #328 is ready to close after this documentation reconciliation PR is
merged and the broad CI gate passes.

The backend now has a real DSR foundation, export workflow, erase execution
boundary, export artifact retention runner, S3-compatible export storage,
inventory-aligned runtime/policy erasure coverage, preserved provider decisions
and contract tests that keep the erasure inventory, coverage map, orchestrator,
impact preview and privacy docs aligned.

The current erasure orchestrator now executes or records policy coverage for:

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
  timestamps and reviewer.
- Platform DSR APIs protected by privacy permissions.
- User self-service DSR APIs.
- Export service through cross-table subject export providers.
- Export coverage for user profile, memberships, organisations, invites,
  outbox, audit, DSR/export metadata and privacy-governance records.
- Export artifact delivery through queued artifacts, worker command, dedicated
  rate limits and short-lived URLs.
- Production-grade export object storage option through S3-compatible storage
  with opt-in MinIO integration coverage.
- Export artifact retention through the retention runner.
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
- Self-erasure audit actor leakage guard.
- Successful erase fulfilment after inventory-aligned erasure execution.
- Contract tests proving inventory/export alignment.
- Tests proving erasure removes/minimises or policy-covers all inventoried
  personal-data stores through runtime and contract coverage tests.

## Closure blockers

No current implementation or documentation blocker remains for the backend #328
scope after this documentation reconciliation PR.

Final closure action:

- Priority: P1.
- Required command before closing: `task ci`.

## Non-blocking follow-up issues

These should remain separate from the #328 closure blockers:

- Add streaming archive generation for DSR exports.
  - Priority: P2.
  - Rationale: large production exports need streaming, but this does not block
    basic DSR workflow correctness.
- Add PostgreSQL export-provider integration coverage.
  - Priority: P2.
  - Rationale: default tests should remain fast; PostgreSQL JSON predicate
    coverage belongs in external-db tests.
- Add explicit delivery evidence events.
  - Priority: P2.
  - Rationale: current download URL/download count inference may be insufficient
    for formal evidence workflows.
- Add authorised representative workflows.
  - Priority: P2.
  - Rationale: requires product policy, identity verification and authority
    evidence.
- Add frontend/UI for DSR workflows.
  - Priority: P2.
  - Rationale: current project scope is backend-only.
- Add execution pipelines for rectify/restrict/object/access/portability.
  - Priority: P2.
  - Rationale: request types exist, but fulfilment should remain blocked until
    concrete execution policies exist.

## Verification commands

Recommended before closing #328:

```bash
task ci
```

Focused commands for this area:

```bash
cd backend
uv run --locked pytest -q -m "privacy and not external_db"
uv run --locked pytest -q -m contract
uv run --locked pytest -q tests/contracts/test_privacy_docs_contract.py
```
