# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-07-03
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
| 10 | Final #328 closure reconciliation | Yes | Not started |

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
Status: Patch prepared; not merged.

### Prepared scope

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

## Final #328 closure reconciliation

Status: Not started.

### Remaining scope

After PR-328-9C is merged:

1. Re-run full CI.
2. Check issue #328 against all child/follow-up work.
3. Update the closure checklist.
4. Close #328 only if no P0-P2 privacy/DSR implementation gaps remain.

## Notes for future agents

- Keep PRs small and do not combine unrelated privacy, invite, ops and runtime
  hardening work.
- Documentation can lag code; always verify `main` before changing scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Do not close #328 until every roadmap item is done or explicitly removed from
  #328 scope by a documented decision.
