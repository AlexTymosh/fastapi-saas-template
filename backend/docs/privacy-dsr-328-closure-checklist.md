# Issue #328 closure checklist

## Scope

This document maps the original issue #328 requirements to the implemented
backend scope.

The issue asked for a coordinated Data Subject Rights workflow that can respond
to subject requests and avoid manual database operations across current
personal-data stores.

## Requirement mapping

| #328 requirement | Current status |
|---|---|
| Dedicated privacy/DSR module | Implemented under `backend/app/privacy`. |
| `DataSubjectRequest` model with request type, requester, subject, status, timestamps and reviewer | Implemented. |
| Platform DSR APIs protected by privacy permissions | Implemented. |
| User self-service DSR APIs | Implemented. |
| Export service for current subject data | Implemented through cross-table subject export providers. |
| Export coverage for user profile | Implemented. |
| Export coverage for memberships and organisations | Implemented. |
| Export coverage for invites | Implemented with token minimisation. |
| Export coverage for outbox references | Implemented with payload minimisation. |
| Export coverage for audit events | Implemented with unrelated actor/context minimisation. |
| Export artifact delivery flow | Implemented through queued artifacts, worker command and short-lived URLs. |
| Production-grade export object storage option | Implemented through S3-compatible storage. |
| Erasure/anonymisation service | Implemented through provider orchestration. |
| User profile erasure | Implemented. |
| Invite erasure/minimisation | Implemented. |
| Outbox payload scrubbing | Implemented. |
| Audit record minimisation while retaining integrity | Implemented. |
| Platform erasure execution API | Implemented. |
| Self-erasure audit actor leakage guard | Implemented. |
| Successful erase fulfilment | Implemented. |
| Export artifact retention | Implemented through retention runner. |
| Contract tests proving inventory/export alignment | Implemented. |
| Tests proving erasure removes/minimises current PII stores | Implemented across erasure provider, orchestration, command and API tests. |

## Closure decision

Issue #328 can be closed for the current backend scope after CI passes on the PR
that adds this checklist.

The remaining items below should not block #328 closure because they are broader
production hardening or product-scope extensions rather than missing backend DSR
workflow primitives.

## Follow-up issues to create separately

| Follow-up | Priority | Rationale |
|---|---:|---|
| Add streaming archive generation for DSR exports | P2 | Current export generation is acceptable for template-scale data, but large production exports need streaming. |
| Add PostgreSQL export-provider integration coverage | P2 | Default tests should remain fast; PostgreSQL JSON predicate coverage belongs in external-db tests. |
| Add explicit delivery evidence events | P2 | Current download URL/download count inference may be insufficient for formal evidence workflows. |
| Add authorised representative workflows | P2 | Requires product policy, identity verification and authority evidence. |
| Add frontend/UI for DSR workflows | P2 | Current project scope is backend-only. |
| Add execution pipelines for rectify/restrict/object/access/portability | P2 | Request types exist, but fulfilment should remain blocked until concrete execution policies are implemented. |

## Verification commands

Recommended before closing #328:

```bash
task ci
```

Focused commands for this area:

```bash
cd backend
uv run --locked pytest -q tests/privacy
uv run --locked pytest -q tests/platform/test_platform_permissions.py
```
