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
- Erasure provider plan and preview.
- Executable erasure providers for user profile, invites, outbox and audit
  minimisation.
- Core erasure orchestrator and command-layer execution boundary.
- Platform erasure execution API.
- Self-erasure execution rejection before provider orchestration.
- Automatic fulfilment after successful approved erase execution.
- Export artifact retention runner that deletes expired archive objects and
  clears storage metadata.

Issue #328 is still not ready for closure. The executable erasure workflow does
not yet cover every personal-data store declared by the erasure inventory.

## Remaining quality gaps

| Finding | Priority | Required action |
|---|---:|---|
| Executable erasure covers audit, outbox, invites and users only. | P1 | Add executable providers or explicit manual-review policy for the remaining inventory targets. |
| Membership and organisation subject links are inventoried but not executed. | P1 | Implement minimisation/review providers before closing #328. |
| Platform staff, DSR/export-artifact and privacy-governance records are inventoried but not executed. | P1 | Implement safe minimisation or documented retention/manual-review rules. |
| Export generation still builds the subject payload and ZIP in memory. | P2 | Add streaming archive generation before supporting large production exports. |
| PostgreSQL-specific JSON predicate behaviour is not covered by default tests. | P2 | Add an external-db test for outbox JSON matching and audit target joins. |
| Delivery evidence is inferred from download URL/download count. | P2 | Add explicit delivery event semantics if formal receipt evidence becomes required. |
| Rectification, restriction, objection, access and portability execution pipelines are not implemented. | P2 | Keep those request types reviewable but not fulfilment-ready until concrete execution policies exist. |
| Authorised representative workflows are not implemented. | P2 | Add a separate representative authority and verification workflow if the product needs it. |
| No frontend/UI is implemented. | P2 | Build UI separately; current scope is backend-only. |

## Recommended next branch

Use a small implementation branch before closing #328:

```text
privacy/dsr-erasure-remaining-inventory-coverage
```

Scope:

1. Add executable provider coverage or explicit manual-review rules for:
   - memberships;
   - organisations;
   - platform staff;
   - DSR/export-artifact records;
   - privacy-governance records.
2. Extend orchestration tests to prove those targets are handled.
3. Update the erasure closure checklist only after the executable coverage and
   tests are in place.

## Decomposition warning

The remaining #328 closure work should not be collapsed into this documentation
PR.

Recommended order:

1. Close the current documentation overclaim in PR #406.
2. Implement remaining erasure inventory coverage in a dedicated runtime PR.
3. Add coverage tests for the newly executable erasure targets.
4. Revisit the #328 closure checklist after those tests pass.
5. Close #328 only when executable erasure coverage matches the documented
   privacy inventory or the remaining items have explicit manual-review policy.
