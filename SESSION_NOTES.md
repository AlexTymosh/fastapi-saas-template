# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-07-07
Repository: `AlexTymosh/fastapi-saas-template`
Branch used for verification: `main`
Parent issue: `#328`

## Current decision

Do not close #328 yet. The project owner wants full closure after all known
privacy/DSR P2 follow-up work is completed, not only backend-foundation closure.

## Current verified state

- PR #426 is merged into `main`.
- PR-328-1 is done: non-export/non-erase request types are review-only.
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
- PR #437 is open for PR-328-10A. Codex review follow-up is prepared for
  invite/outbox batch starvation and audit legal-hold recheck gaps.

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
| 10A | Expand retention beyond export artifacts | Yes | Prepared in this patch |
| 10B | DSR operations visibility | Yes | Not started |
| 10C | DSR permission contract cleanup | Yes | Not started |
| 10D | Provider contract alignment | Yes | Not started |
| 10E | Batched subject export providers | Yes | Not started |
| 10F | Final #328 closure reconciliation | Yes | Not started |

## PR-328-9A — Authorised representative DSR intake

Priority: P2
Type: `feat(privacy)`
Branch: `feat/privacy-dsr-representative-intake`
PR title: `✨ feat(privacy): add representative DSR intake guardrails`
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
Branch: `feat/privacy-dsr-representative-intake`
PR title: `✨ feat(privacy): add representative DSR review workflow`
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
Recommended branch: `test/privacy-dsr-representative-fulfilment`
Recommended PR title: `🧹 chore(privacy): cover representative DSR fulfilment`
Status: Done in merged PR #435; re-verified after merge.

### Delivered scope

1. Add regression coverage proving verified representative export artifacts are
   built from represented subject data.
2. Prove representative export artifacts are requester-owned, not subject-owned.
3. Prove represented subjects cannot read representative-owned artifacts through
   own-artifact endpoints.
4. Prove representative erase DSRs erase the represented subject, not the
   representative requester.
5. Document fulfilment/export/erasure semantics for representative DSRs.

### Failure cases to cover

- Export generation accidentally uses representative requester data.
- Export artifact ownership is accidentally changed from requester to subject.
- Represented subject can download a representative-owned artifact.
- Erasure execution accidentally erases the representative requester.
- Fulfilment semantics drift without documentation.

## PR-328-10A — Expand retention beyond export artifacts

Priority: P1
Type: `feat(privacy)`
Recommended branch: `privacy/dsr-retention-maintenance-hardening`
Recommended PR title: `✨ feat(privacy): expand DSR retention maintenance`
Status: Open in PR #437; Codex review follow-up patch prepared.

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
- Invite retention filters already-retained rows before applying the batch cap.
- Outbox retention filters already-scrubbed rows before applying the batch cap.
- Outbox `pending` and `processing` rows are excluded to avoid delivery races.
- Audit rows under active legal hold are excluded from retention minimisation.
- Audit bulk updates recheck legal-hold eligibility at mutation time.
- Export artifact object deletion remains delegated to `ExportArtifactService`.
- Storage-deleting export artifact retention runs after database-only retention
  steps to avoid rollback/storage inconsistency if a later DB step fails.

### Codex review follow-up

1. Fixed invite batch starvation by pushing the needs-retention predicate into
   the SQL query before `LIMIT`.
2. Fixed outbox batch starvation by pushing the already-scrubbed marker and
   failed-error checks into the SQL query before `LIMIT`.
3. Fixed the audit legal-hold race by reusing the audit eligibility predicates
   in the bulk `UPDATE`, not only during ID selection.
4. Added regression tests for all three failure cases.
5. Fixed storage rollback inconsistency by running storage-deleting export
   artifact retention after database-only invite/outbox/audit/DSR steps.

## Final #328 closure reconciliation

Status: Not ready. Continue with PR-328-10B through PR-328-10F.

### Remaining scope

1. Add DSR operations visibility for failed/stale export and erasure execution.
2. Resolve the legacy `GDPR_EXPORT` / `GDPR_ERASE` permission contract drift.
3. Align provider inventory, runtime provider registries and erasure coverage.
4. Remove high-cardinality eager `.all()` loading from subject export providers.
5. Re-run full CI.
6. Update the closure checklist.
7. Close #328 only if no P0-P2 privacy/DSR implementation gaps remain.

## Notes for future agents

- Keep PRs small and do not combine unrelated privacy, invite, ops and runtime
  hardening work.
- Documentation can lag code; always verify `main` before changing scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Do not close #328 until every roadmap item is done or explicitly removed from
  #328 scope by a documented decision.
