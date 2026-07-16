# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-07-14
Repository: `AlexTymosh/fastapi-saas-template`
Branch used for verification: `main`
Parent issue: `#328`

## Current decision

Issue #328 is ready for project-owner closure after this final documentation
reconciliation PR is merged and `task ci` passes on the resulting branch.

The backend #328 scope now has no known P0-P2 implementation or documentation
blocker. Future `export.json` schema contract, product/UI or storage-native
evidence work should be tracked as separate follow-up issues, not as #328
blockers.

## Current verified state

- PR #426 is merged into `main`.
- PR-328-1 is done: non-export/non-erase request types are review-only and
  cannot be approved until a concrete execution policy exists.
- PR #427 is merged into `main`.
- PR-328-2 is done: self-service DSR submissions accept requester details.
- PR #428 is merged into `main`.
- PR-328-3 is done: URL issuance is separated from confirmed delivery evidence.
- PR #429 is merged into `main`.
- PR-328-4 is done: invite delivery has an SMTP provider and NoOp guardrails.
- PR #430 is merged into `main`.
- PR-328-5 is done: retention runner Taskfile commands and ops docs are merged.
- PR #431 is merged into `main`.
- PR-328-6 is done: backend container runtime hardening baseline is merged.
- PR #432 is merged into `main`.
- PR-328-7 is done: PostgreSQL DSR provider integration tests are merged.
- PR #433 is merged into `main`.
- PR-328-8 is done: DSR export archive generation streams through temp files.
- PR #434 is merged into `main`.
- PR-328-9A is done: authorised representative DSR intake is merged.
- PR-328-9B is done: representative authority review workflow is merged.
- PR #435 is merged into `main`.
- PR-328-9C is done: representative fulfilment/export/erasure semantics are
  covered.
- PR #436 is merged into `main`.
- Runtime secret masking hardening is done.
- PR #437 is merged into `main`.
- PR-328-10A is done: retention maintenance covers export artifacts, invite
  lifecycle rows, delivered/failed outbox payloads, old audit context and
  expired DSR idempotency metadata.
- PR #438 is merged into `main`.
- PR-328-10B is done: DSR execution health visibility, metrics, logs and CLI
  operator checks are merged.
- PR #439 is merged into `main`.
- PR-328-10C is done: legacy generic GDPR permissions were removed from the
  runtime platform permission contract and current docs.
- PR #440 is merged into `main`.
- PR-328-10D is done: provider keys, inventory, runtime export providers,
  provider registry, erasure coverage and actual erasure provider result order
  are covered by one alignment contract.
- PR #441 is merged into `main`.
- PR-328-10E is done: subject export providers use bounded keyset/batched
  iteration instead of unbounded eager provider result loading, and email-based
  invite helper subqueries use trim/lower normalisation.
- PR-328-10F is done in this patch: final #328 documentation, current-state
  notes, historical follow-up notes and closure checklist are reconciled against
  the current backend implementation.

## Roadmap status

| Order | PR | Blocks #328 closure | Status |
|---:|---|---:|---|
| 1 | Define execution policy for non-export DSR types | Yes | Done |
| 2 | Accept requester details on DSR submissions | Yes | Done |
| 3 | Separate URL issuance from delivery evidence | Yes | Done |
| 4 | Real invite delivery provider / NoOp guard | Yes | Done |
| 5 | Retention runner Taskfile and ops docs | Yes | Done |
| 6 | Runtime secrets and Docker hardening | Yes | Done |
| 7 | PostgreSQL DSR provider integration tests | Yes | Done |
| 8 | Streaming DSR export archive generation | Yes | Done |
| 9 | Authorised representative DSR workflow | Yes | Done |
| 10A | Expand retention beyond export artifacts | Yes | Done |
| 10B | DSR operations visibility | Yes | Done |
| 10C | DSR permission contract cleanup | Yes | Done |
| 10D | Provider contract alignment | Yes | Done |
| 10E | Batched subject export providers | Yes | Done |
| 10F | Final #328 closure reconciliation | Yes | Done |

## PR-328-9A — Authorised representative DSR intake

Priority: P2
Type: `feat(privacy)`
Status: Done in merged PR #434; re-verified after merge.

### Delivered scope

1. Added representative intake metadata to `data_subject_requests`.
2. Preserved current self-service behaviour as the default DSR submission path.
3. Allowed explicit representative submissions with subject, relationship and
   authority details.
4. Stored representative submissions as `pending_verification`.
5. Blocked approval until representative authority is verified.
6. Included representative intake metadata in idempotency fingerprints.
7. Validated represented subject users before DSR insert.
8. Preserved pre-upgrade self-service idempotency retries during the TTL window.

## PR-328-9B — Platform representative authority verification

Priority: P2
Type: `feat(privacy)`
Status: Done in merged PR #434; re-verified after merge.

### Delivered scope

1. Added platform representative authority verify/reject endpoints.
2. Kept DSR lifecycle separate from representative authority review state.
3. Added conditional representative authority review writes.
4. Added atomic approval guard on representative status.
5. Added representative-status filtering to platform DSR list/count.
6. Added compliance audit events for representative authority decisions.
7. Included verifier-only DSR workflow rows in subject exports as references.
8. Aligned erasure impact preview and execution predicates for verifier links.

## PR-328-9C — Representative fulfilment/export/erasure semantics

Priority: P2
Type: `test(privacy)`
Status: Done in merged PR #435; re-verified after merge.

### Delivered scope

1. Added regression coverage proving verified representative export artifacts are
   built from represented subject data.
2. Proved representative export artifacts are requester-owned, not subject-owned.
3. Proved represented subjects cannot read representative-owned artifacts through
   own-artifact endpoints.
4. Proved representative erase DSRs erase the represented subject, not the
   representative requester.
5. Documented fulfilment/export/erasure semantics for representative DSRs.

## PR-328-10A — Expand retention beyond export artifacts

Priority: P1
Type: `feat(privacy)`
Status: Done in merged PR #437.

### Delivered scope

1. Replaced the single-purpose export artifact retention helper with a bounded
   `run_privacy_retention_maintenance()` orchestration helper.
2. Preserved `expire_ready_export_artifacts()` for backward-compatible callers
   and existing tests.
3. Added invite lifecycle retention for accepted, expired and revoked invite rows:
   email/token tombstones, `expires_at` cleanup and `revoked_by_user_id`
   minimisation.
4. Added delivered/failed outbox payload scrubbing after the delivery retention
   window while leaving pending/processing rows untouched.
5. Added audit minimisation for old non-held audit rows: actor link, free-form
   reason, metadata, IP address and user-agent are removed while action/timestamp
   integrity remains.
6. Added expired DSR idempotency metadata cleanup.
7. Updated `privacy:retention:*` Taskfile descriptions and CLI output so the
   command reports a per-step retention summary instead of export-only counts.
8. Expanded privacy retention regression tests for dry-run safety and apply mode.
9. Added `docs/privacy-dsr-retention.md` with operator guidance and boundaries.

### Regression boundaries

- The runner does not commit; transaction ownership stays with the caller.
- Dry-run mode must not mutate DB rows or delete storage objects.
- Invite and outbox retention filter already-retained rows before applying the
  batch cap.
- Outbox `pending` and `processing` rows are excluded to avoid delivery races.
- Audit rows under active legal hold are excluded from retention minimisation.
- Audit bulk updates recheck legal-hold eligibility at mutation time.
- Export artifact object deletion remains delegated to `ExportArtifactService`.
- Storage-deleting export artifact retention runs after database-only retention
  steps to avoid rollback/storage inconsistency if a later DB step fails.

## PR-328-10B — DSR operations visibility

Priority: P1
Type: `feat(privacy)`
Status: Done in merged PR #438.

### Delivered scope

1. Added read-only DSR execution health snapshots.
2. Counted export and erase DSR jobs by execution status.
3. Reported current failed/stale DSR and export artifact signals.
4. Added low-cardinality metrics, structured logs and `task privacy:dsr-health`.
5. Moved aggregate database reads into a dedicated read-model repository.
6. Added Windows-compatible CLI event-loop handling for Psycopg async.
7. Preserved failed and partially fulfilled metric statuses.
8. Excluded cancelled DSR work from current degraded signals.
9. Added explicit CLI transaction, observability initialization and shutdown
   coverage.
10. Documented operator usage in `docs/privacy-dsr-operations.md`.

### Regression boundaries

- Health snapshots are read-only and do not mutate DSR or export artifact rows.
- Metrics use bounded attributes only.
- Logs expose aggregate counts only and do not include per-subject identifiers.
- Cancelled, superseded and delivered historical rows do not degrade current
  snapshots.
- CLI observability shutdown still runs after snapshot failures when
  initialization succeeded.

## PR-328-10C — DSR permission contract cleanup

Priority: P1
Type: `security(privacy)`
Status: Done in merged PR #439.

### Delivered scope

1. Removed legacy generic GDPR permission values from `PlatformPermission`.
2. Added `privacy_export_artifacts:manage` as the dedicated platform boundary for
   export artifact creation, platform download URL generation and delivery
   confirmation.
3. Kept approved erase execution on `privacy_requests:execute_erasure`.
4. Updated compliance-officer role mapping to include the new export artifact
   management permission and no generic GDPR permissions.
5. Updated platform privacy routes to use the dedicated export artifact manage
   permission for mutating export artifact operations.
6. Updated current DSR and platform access docs to match the runtime permission
   contract.
7. Added regression tests proving legacy GDPR values are absent from the runtime
   permission enum, docs and export-artifact route dependencies.

### Regression boundaries

- Support agents still cannot read, manage or execute privacy DSR operations.
- Compliance officers can still read/review DSRs, manage export artifacts and
  execute approved erasure through explicit privacy boundaries.
- Platform admins keep all current platform permissions via `ALL_PERMISSIONS`.
- Export artifact read routes still require the read-specific permission.
- Export artifact mutating routes use the manage-specific permission and do not
  reuse the read boundary.

## PR-328-10D — Provider contract alignment

Priority: P1
Type: `test(privacy)`
Status: Done in merged PR #440.

### Delivered scope

1. Added `export_provider_order()` to the central provider-key catalogue.
2. Added regression coverage tying privacy inventory export keys to the central
   export provider catalogue.
3. Added regression coverage tying privacy inventory erasure keys to the central
   erasure provider catalogue.
4. Added table-mapping checks between inventory rows and central provider-key
   table mappings.
5. Added runtime export provider checks for provider order and table names.
6. Added provider registry checks proving the derived registry contains only
   central catalogue keys.
7. Added erasure coverage checks proving the coverage map still matches the
   central erasure provider catalogue.
8. Added a regression test that calls `_run_core_providers()` with patched
   providers and asserts the actual emitted provider result order.
9. Added `backend/docs/privacy-provider-registry.md` with the provider alignment
   contract and change rule.

### Regression boundaries

- Adding an inventory export provider without a central provider-key entry fails
  the provider alignment contract.
- Adding an inventory erasure provider without a central provider-key entry fails
  the provider alignment contract.
- Runtime export provider order must match the central export provider order.
- Runtime export provider table names must match central table mapping.
- The derived provider registry must not contain ad-hoc keys outside the central
  export/erasure catalogues.
- The actual `_run_core_providers()` emitted provider result order must match
  the central erasure provider order; wrapper-only order checks are not enough.

## PR-328-10E — Batched subject export providers

Priority: P1
Type: `perf(privacy)`
Status: Done in merged PR #441.

### Delivered scope

1. Replaced unbounded multi-row subject export provider `.all()` calls with
   bounded keyset page iteration.
2. Added deterministic keyset ordering by provider ordering column and `id`
   tie-breaker.
3. Replaced Python-side ID materialisation for audit/outbox helper lookups with
   SQL subqueries where possible.
4. Preserved provider payload shape, provider ordering and redaction behaviour.
5. Added regression coverage proving subject export provider source does not use
   eager `.all()` loading.
6. Added a batching regression test that forces multiple authorization export
   pages and verifies deterministic ordering across page boundaries.
7. Normalised email-based invite subqueries used by audit/outbox lookup paths so
   legacy mixed-case or padded subject emails keep matching subject-linked
   invites.
8. Added regression coverage for audit invite lookup with a non-normalised local
   user email.
9. Updated `backend/docs/privacy-dsr-export-providers.md` with the provider
   iteration model, email normalisation and guardrails.

### Regression boundaries

- Multi-row subject export providers must not use unbounded eager `.all()`
  result loading.
- Provider pagination must use deterministic ordering and an `id` tie-breaker so
  rows are neither skipped nor duplicated across batch boundaries.
- SQL helper lookups should avoid loading large ID lists into Python when a
  subquery can preserve the same predicate.
- Email-based helper subqueries must use the same trim/lower normalisation as
  direct provider lookups.
- Existing export payload shape and redaction fields remain unchanged.

## PR-328-10F — Final #328 closure reconciliation

Priority: P1
Type: `docs(privacy)`
Status: Done in this patch.

### Delivered scope

1. Reconciled `backend/docs/privacy-dsr-328-closure-checklist.md` with the actual
   merged backend state after PRs #426 through #441.
2. Removed stale non-blocking follow-up entries that are now implemented:
   streaming archive generation, PostgreSQL provider integration coverage,
   explicit export delivery evidence and authorised representative workflow.
3. Kept versioned export payload schema contract, frontend/UI, storage-native
   delivery evidence and non-export execution pipelines as separate post-#328
   follow-up categories.
4. Updated `backend/docs/current-state.md` and `backend/docs/privacy-dsr.md` so
   they reflect DSR operations visibility, expanded retention, permission
   cleanup, provider alignment and batched export providers.
5. Updated historical follow-up notes so they do not present implemented work as
   remaining #328 scope.
6. Added docs-contract coverage for the final checklist and implemented
   follow-up categories.
7. Corrected current-state ops guide paths so retention and DSR health operator
   guides point to root `docs/`, where those files actually live.
8. Kept the versioned `export.json` payload schema contract as a tracked
   post-#328 follow-up rather than treating it as completed backend scope.

### Regression boundaries

- Documentation must not claim #328 is closed before this PR is merged and
  `task ci` passes.
- Documentation must not list already-implemented #328 backend work as a
  remaining blocker or non-blocking follow-up.
- Documentation must keep the export schema contract, frontend/UI and future
  storage-native evidence as separate post-#328 follow-ups.
- Documentation must keep review-only DSR request types blocked from approval
  until concrete execution policies exist.
- Current-state documentation must point to existing operator guide paths and
  must not index root `docs/` guides under `backend/docs/`.

## Final #328 closure reconciliation

Status: Ready after this PR and a green `task ci` run.

### Remaining closure action

1. Merge this documentation reconciliation PR.
2. Run `task ci` on the resulting branch.
3. Close #328 if no new P0-P2 regression appears during CI or review.

## Notes for future agents

- Keep future privacy work out of #328 unless the project owner explicitly
  reopens the issue scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Treat historical implementation-slice notes as context only; current closure
  truth is in `backend/docs/privacy-dsr.md`,
  `backend/docs/privacy-dsr-328-closure-checklist.md`,
  `backend/docs/current-state.md` and this file.
