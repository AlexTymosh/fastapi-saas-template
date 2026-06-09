# Issue #328 closure readiness checklist

## Scope

This document maps the original issue #328 requirements to the current backend
implementation and the remaining blockers.

The issue asked for a coordinated Data Subject Rights workflow that can respond
to subject requests and avoid manual database operations across current
personal-data stores.

## Current decision

Issue #328 must remain open.

The backend now has a real DSR foundation, export workflow, erase execution
boundary, and export artifact retention runner. However, the executable erasure
coverage is still narrower than the declared privacy inventory.

The current erasure orchestrator executes only these providers:

- `audit.minimise_subject_actor_or_target_identifiers`
- `outbox.purge_or_scrub_payload`
- `invites.anonymise_or_purge_subject_references`
- `users.anonymise_profile`

The privacy inventory and erasure preview still declare wider erasure coverage,
including membership, organisation, platform staff, DSR, export-artifact, and
privacy-governance records. Closing #328 before executable providers or explicit
manual-review rules exist for those areas would overstate the erasure workflow.

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
| Erasure/anonymisation service | Partially implemented. Executable orchestration covers audit, outbox, invites and user profile only. |
| User profile erasure | Implemented. |
| Invite erasure/minimisation | Implemented. |
| Outbox payload scrubbing | Implemented. |
| Audit record minimisation while retaining integrity | Implemented. |
| Membership erasure/minimisation | Not implemented as an executable provider. |
| Organisation subject-reference handling | Not implemented as an executable provider. |
| Platform staff subject-reference handling | Not implemented as an executable provider. |
| DSR/export-artifact subject-reference handling during erasure | Not implemented as an executable provider. |
| Privacy-governance record handling during erasure | Not implemented as an executable provider. |
| Platform erasure execution API | Implemented for the current executable providers. |
| Self-erasure audit actor leakage guard | Implemented. |
| Successful erase fulfilment | Implemented for the current executable provider set only. |
| Contract tests proving inventory/export alignment | Implemented. |
| Tests proving erasure removes/minimises all inventoried personal-data stores | Not complete. Current tests cover only implemented erasure providers. |

## Closure blockers

These items must be resolved before closing #328:

| Blocker | Priority | Required action |
|---|---:|---|
| Executable erasure coverage does not match the erasure inventory. | P1 | Add providers or explicit manual-review rules for all inventoried erasure targets. |
| Membership and organisation subject links are not minimised by execution. | P1 | Implement provider(s) or document legally required retention/manual review. |
| Platform staff and privacy-governance subject records are not handled by execution. | P1 | Implement provider(s) or explicit non-erasure policy. |
| DSR/export-artifact subject references are not handled by execution. | P1 | Implement safe minimisation rules that preserve operational evidence. |
| Closure docs currently risk overstating backend DSR completion. | P2 | Keep this checklist as a readiness document, not a closure declaration. |

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
