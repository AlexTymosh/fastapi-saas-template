# Issue #328 closure readiness checklist

## Scope

This document maps the original issue #328 requirements to the current backend
implementation and the remaining blockers.

The issue asked for a coordinated Data Subject Rights workflow that can respond
to subject requests and avoid manual database operations across current
personal-data stores.

## Current decision

Issue #328 should remain open until the final closure-review issue completes.

The backend now has a real DSR foundation, export workflow, erase execution
boundary, export artifact retention runner, inventory-aligned runtime/policy
erasure coverage, and contract tests that keep the erasure inventory, coverage
map, orchestrator and impact preview aligned.

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

Membership and organisation handling is intentionally policy-based rather than
destructive because those rows preserve tenant and compliance integrity.

## Requirement mapping

| #328 requirement | Current status |
|---|---|
| Dedicated privacy/DSR module | Implemented under `backend/app/privacy`. |
| `DataSubjectRequest` model with request type, requester, subject, status, timestamps and reviewer | Implemented. |
| Platform DSR APIs protected by privacy permissions | Implemented. |
| User self-service DSR APIs | Implemented. |
| Export service for current subject data | Implemented through cross-table subject export providers. |
| Export coverage for user profile, memberships, organisations, invites, outbox, audit, DSR/export metadata and privacy-governance records | Implemented for the current export scope. |
| Export artifact delivery flow | Implemented through queued artifacts, worker command and short-lived URLs. |
| Production-grade export object storage option | Implemented through S3-compatible storage. |
| Export artifact retention | Implemented through retention runner. |
| Erasure/anonymisation service | Implemented for the declared inventory through executable minimisation providers plus explicit retain/manual-review policies. |
| User profile erasure | Implemented. |
| Invite erasure/minimisation | Implemented. |
| Outbox payload scrubbing | Implemented. |
| Audit record minimisation while retaining integrity | Implemented. |
| Membership erasure/minimisation | Covered by explicit retain-and-minimise policy; linked user profile is anonymised. |
| Organisation subject-reference handling | Covered by tenant-owned manual-review policy. |
| Platform staff subject-reference handling | Implemented for nullable creator links and free-text suspension context. |
| DSR/export-artifact subject-reference handling during erasure | Implemented for workflow and artifact metadata minimisation. |
| Privacy-governance record handling during erasure | Implemented through source-field minimisation plus retention of compliance evidence. |
| Platform erasure execution API | Implemented for the current executable providers. |
| Self-erasure audit actor leakage guard | Implemented. |
| Successful erase fulfilment | Implemented after inventory-aligned erasure execution succeeds. |
| Contract tests proving inventory/export alignment | Implemented. |
| Tests proving erasure removes/minimises or policy-covers all inventoried personal-data stores | Implemented through runtime and contract coverage tests. |

## Closure blockers

Remaining item before closing #328:

| Blocker | Priority | Required action |
|---|---:|---|
| Final closure review has not been completed after the #407/#408 runtime and contract-test changes. | P1 | Run the agreed broad CI gate, reconcile issue metadata/docs, and close #328 only if no regressions remain. |

## Non-blocking follow-up issues

These should remain separate from the #328 closure blockers:

| Follow-up | Priority | Rationale |
|---|---:|---|
| Add streaming archive generation for DSR exports | P2 | Large production exports need streaming, but this does not block basic DSR workflow correctness. |
| Add PostgreSQL export-provider integration coverage | P2 | Default tests should remain fast; PostgreSQL JSON predicate coverage belongs in external-db tests. |
| Add explicit delivery evidence events | P2 | Current download URL/download count inference may be insufficient for formal evidence workflows. |
| Add authorised representative workflows | P2 | Requires product policy, identity verification and authority evidence. |
| Add frontend/UI for DSR workflows | P2 | Current project scope is backend-only. |
| Add execution pipelines for rectify/restrict/object/access/portability | P2 | Request types exist, but fulfilment should remain blocked until concrete execution policies exist. |

## Verification commands

Recommended before merging DSR documentation changes:

```bash
task ci
```

Focused commands for this area:

```bash
cd backend
uv run --locked pytest -q tests/privacy
uv run --locked pytest -q tests/platform/test_platform_permissions.py
```
