# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-06-27
Repository: `AlexTymosh/fastapi-saas-template`
Branch used for verification: `main`
Parent issue: `#328`

## Current decision

Do not close #328 yet. The project owner wants full closure after all known
privacy/DSR P2 follow-up work is completed, not only backend-foundation closure.

## Current verified state

- PR #426 is merged into `main`.
- PR-328-1 is done: non-export/non-erase request types are review-only.
- Approval for request types without execution policy is blocked in the central
  DSR service transition path.
- PR #427 is merged into `main`.
- PR-328-2 is done: self-service DSR submissions accept `requester_note`,
  normalise blank notes, keep user responses minimal and expose notes only to
  authorised platform reviewers.
- PR-328-3 files prepared: URL issuance is separated from delivery evidence
  through dedicated URL-issue metadata and explicit delivery confirmation.

## Roadmap status

| Order | PR | Blocks #328 closure | Status |
|---:|---|---:|---|
| 1 | Define execution policy for non-export DSR types | Yes | Done |
| 2 | Accept requester details on DSR submissions | Yes | Done |
| 3 | Separate URL issuance from delivery evidence | Yes | In PR #428; Codex feedback addressed locally |
| 4 | Real invite delivery provider / NoOp guard | Yes | Not started |
| 5 | Retention runner Taskfile and ops docs | Yes | Not started |
| 6 | Runtime secrets and Docker hardening | Yes | Not started |
| 7 | PostgreSQL DSR provider integration tests | Yes | Not started |
| 8 | Streaming DSR export archive generation | Yes | Not started |
| 9 | Authorised representative DSR workflow | Yes | Not started |
| 10 | Final #328 closure reconciliation | Yes | Not started |

## PR-328-3 — Separate URL issuance from delivery evidence

Priority: P2
Type: `feat(privacy)`
Recommended branch: `feat/privacy-export-delivery-evidence`
Recommended PR title: `✨ feat(privacy): separate export URL issuance from delivery evidence`

### Goal

A generated download URL proves only that the application issued a short-lived
access URL. It must not be treated as proof that the export artifact was
received. Delivery evidence is now explicit.

### Implementation plan

1. Add export artifact URL-issuance metadata:
   - `download_url_issued_at`;
   - `download_url_issue_count`.
2. Keep `downloaded_at` and `download_count` for confirmed delivery only.
3. Generate download URLs without marking DSR execution as `delivered`.
4. Add self-service and platform `confirm-delivery` endpoints.
5. Mark the export DSR execution as `delivered` only after delivery
   confirmation.
6. Add an audit action for confirmed export delivery.
7. Update API/service tests and docs.

### Failure cases to cover

- URL issued but delivery not confirmed keeps DSR execution state non-delivered.
- Delivery confirmation marks DSR execution as delivered.
- Expired artifacts cannot be confirmed as delivered.
- Another user cannot confirm delivery for someone else's export artifact.
- Multiple URL issuances increase URL issue metadata without increasing delivery
  count.
- Existing download URL rate limits still apply to URL issuance and delivery
  confirmation endpoints.


### PR #428 Codex feedback addressed locally

- Added `download_url_issued_at` and `download_url_issue_count` to
  `backend/app/privacy/column_inventory.py` so the column inventory covers the
  new export-artifact ORM fields with explicit export/erasure classifications.
- Added the existing authorised artifact-scoped throttle to both
  confirm-delivery routes after artifact authorisation and before delivery
  evidence is written.
- Added route source tests to prove confirm-delivery calls the same
  artifact-scoped throttle before `confirm_export_delivery()`.

## Notes for future agents

- Keep PRs small and do not combine unrelated privacy, invite, ops and runtime
  hardening work.
- Documentation can lag code; always verify `main` before changing scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Do not close #328 until every roadmap item is done or explicitly removed from
  #328 scope by a documented decision.
