# Issue #328 follow-up review

## Current status after PR #405

The current `main` branch has moved beyond the original #328 starting point.

Implemented:

- Data Subject Request persistence, lifecycle fields, repository, service and
  user/platform API.
- Platform permissions for DSR read/review, export artifact operations and
  approved erasure execution.
- Export artifact model, worker command, local storage adapter, S3-compatible
  storage adapter and signed download URL flows.
- DSR architecture inventory contract with table-level and column-level privacy
  declarations.
- Execution-state fields separated from administrative review status.
- Cross-table subject export providers for the current privacy inventory scope.
- Contract tests that align concrete subject export providers with inventory
  export provider keys.
- Erasure provider plan, preview, user profile provider, invite provider, outbox
  provider and audit minimisation provider.
- Core erasure orchestrator and command-layer execution boundary.
- Platform erasure execution API.
- Self-erasure execution rejection before provider orchestration.
- Automatic fulfilment after successful approved erase execution.
- Export artifact retention runner that deletes expired archive objects and
  clears storage metadata.

Issue #328 can now move to final closure review for the current backend scope.

## Remaining quality gaps

These are not blockers for the backend #328 implementation, but they should be
tracked as separate follow-up issues before presenting the project as production
ready.

| Finding | Priority | Required action |
|---|---:|---|
| Export generation still builds the subject payload and ZIP in memory. | P2 | Add streaming archive generation before supporting large production exports. |
| PostgreSQL-specific JSON predicate behaviour is not covered by default tests. | P2 | Add an external-db test for outbox JSON matching and audit target joins. |
| Delivery evidence is inferred from download URL/download count. | P2 | Add explicit delivery event semantics if formal receipt evidence becomes required. |
| Rectification, restriction, objection, access and portability execution pipelines are not implemented. | P2 | Keep those request types reviewable but not fulfilment-ready until concrete execution policies exist. |
| Authorised representative workflows are not implemented. | P2 | Add a separate representative authority and verification workflow if the product needs it. |
| No frontend/UI is implemented. | P2 | Build UI separately; current scope is backend-only. |

## Final #328 closure position

The original issue asked for a dedicated DSR workflow that can safely export and
erase/anonymise current personal data stores without relying on manual database
operations.

That backend requirement is now satisfied for the current implemented product
scope:

- DSR model and lifecycle exist.
- User and platform APIs are registered.
- Export artifacts gather cross-table subject data from the privacy inventory.
- Erasure/anonymisation removes or minimises current user, invite, outbox and
  audit-linked personal data while preserving audit integrity.
- Platform operations are permission protected.
- Export artifact retention removes expired archive objects from storage.
- Contract tests guard inventory, export provider coverage and platform
  permissions.

Do not extend #328 with unrelated production-hardening concerns. Create separate
issues for streaming exports, PostgreSQL integration coverage, representative
flows and frontend work.

## Recommended next action

Create a final PR for #328 closure documentation and, after CI passes, close
issue #328 as completed for the backend scope.
