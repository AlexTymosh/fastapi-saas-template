# Issue #328 follow-up review

## Current status

The current `main` branch has moved significantly beyond the original #328
starting point.

Implemented foundation:

- Data Subject Request persistence, lifecycle fields, repository, service and
  user/platform API.
- Platform permissions for privacy request review and export artifact actions.
- Export artifact model, local storage adapter, worker command and signed local
  download URL flow.
- DSR architecture inventory contract with table-level and column-level privacy
  declarations.
- Execution-state fields separated from administrative review status.
- Fulfilment guard preventing export DSR fulfilment without a ready,
  non-expired export artifact.
- Cross-table subject export providers for the current DSR inventory scope.

Issue #328 is still not fully closed because erasure/anonymisation execution,
production object storage, retention/purge runners and true streaming archive
writing are not implemented yet.

## 328-1 review: architecture inventory contract

Status: mostly complete.

What is good:

- Inventory now covers all current SQLAlchemy model tables or explicitly excludes
  static catalogue tables.
- Core #328 tables are covered: users, memberships, organisations, invites,
  outbox events and audit events.
- Column-level classification exists for direct identifiers, contact points,
  tokens, operational reasons, network identifiers, user agents, metadata and
  lifecycle fields.
- Provider registry metadata is derived from the inventory instead of being an
  unrelated manual list.

Remaining quality gap:

| Finding | Priority | Required action |
|---|---:|---|
| The concrete subject export provider implementation list is not independently checked against the inventory export keys. | P1 | Add a contract test proving every `export_provider_key` in the privacy inventory has exactly one concrete subject export provider and that provider table names match inventory table names. |
| Erasure providers are declared but not implemented. | P0/P1 | Keep #328 open; implement erasure/anonymisation providers in a later branch after production export storage is stable. |
| The provider registry is metadata-only and does not construct runtime providers. | P2 | Acceptable for now, but consider a future registry that can build both export and erasure providers from one source of truth. |

The included test file addresses the first P1 gap without changing public API,
database schema, runtime behaviour or existing export semantics.

## 328-2 review: execution state machine

Status: mostly complete for export DSRs, incomplete for erasure DSRs.

What is good:

- `DataSubjectRequest.execution_status` now exists separately from review
  `status`.
- Export artifact lifecycle updates DSR execution state on queue, processing,
  ready, failed, expired and download/delivery events.
- Direct fulfilment through the generic transition method is blocked.
- `fulfil_request()` now verifies export execution evidence before moving an
  approved DSR to `fulfilled`.
- Ready artifacts remain downloadable for approved and fulfilled DSRs.

Remaining quality gap:

| Finding | Priority | Required action |
|---|---:|---|
| Execution state currently depends on export artifact state, not on a generic DSR execution job model. | P1 | Accept for export MVP; revisit when implementing erasure jobs. Do not overbuild a generic job table before erasure requirements are concrete. |
| Erase, rectify, restrict and object request types can be submitted/reviewed, but execution pipelines are not implemented. | P0 | Keep fulfilment blocked for non-export request types until execution providers exist. |
| `delivered` is currently inferred from download URL generation/download count, which is useful but not equivalent to confirmed human receipt. | P2 | Later add explicit delivery event semantics if the product needs formal evidence of delivery. |

## 328-3 review: subject export providers

Status: partially complete.

What is good:

- The metadata-only export has been replaced with a cross-table export payload.
- Current export provider coverage includes user profile, memberships,
  organisations, invites, outbox references, audit events, DSR records, export
  artifact metadata and privacy-governance records.
- Sensitive fields are redacted or omitted: invite token hashes, outbox raw
  payloads, encrypted raw tokens, storage keys, processing tokens, DSR
  idempotency internals and free-text audit reasons.
- Actor-owned rows are minimised so exports do not leak unrelated subjects.

Remaining quality gap:

| Finding | Priority | Required action |
|---|---:|---|
| Export generation still builds one in-memory `export.json` and one in-memory ZIP archive. | P1 | Implement streaming archive generation before the project can handle large exports safely. |
| Query paths use SQLite-compatible tests; JSON predicate behaviour should also be verified on PostgreSQL. | P1 | Add an external-db/PostgreSQL integration test for outbox JSON matching and audit target joins. |
| The export artifact size limit can fail large SARs after doing all collection work. | P2 | Add preflight record counting or provider-level streaming limits before production use. |
| Export payload schema has no dedicated versioned JSON-schema contract. | P2 | Add schema snapshot/contract docs before exposing this externally. |

## Next recommended branch

Use a small hardening branch before moving to production object storage:

`privacy/dsr-export-provider-contract-hardening`

Scope:

1. Add `backend/tests/privacy/test_subject_export_provider_contract.py`.
2. Run targeted tests:
   - `uv run --frozen pytest -q tests/privacy/test_subject_export_provider_contract.py`
   - `uv run --frozen pytest -q tests/privacy/test_subject_data_exporter.py`
   - `task ci`
3. If green, merge this as a small safety PR.

After that, move to:

`privacy/export-object-storage`

This should implement production-grade object storage instead of extending local
storage semantics.

## Decomposition warning

The remaining #328 work is too large for one PR.

Recommended order:

1. Export provider contract hardening.
2. Production S3-compatible storage adapter and settings validation.
3. Streaming ZIP writer.
4. PostgreSQL export-provider integration tests.
5. Erasure/anonymisation provider planning.
6. Erasure/anonymisation execution.
7. Retention/purge runners for artifacts, outbox and audit minimisation.
8. Final #328 closure checklist.
