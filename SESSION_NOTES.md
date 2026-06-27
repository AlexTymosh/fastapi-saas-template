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
- `approve_request()` is a thin wrapper over `transition_status()`.
- `export` and `erase` remain approvable and executable under the current
  policies.
- `access`, `rectify`, `restrict`, `object` and `portability` can be submitted,
  reviewed, rejected and cancelled, but cannot be approved or fulfilled.

## Roadmap status

| Order | PR | Blocks #328 closure | Status |
|---:|---|---:|---|
| 1 | Define execution policy for non-export DSR types | Yes | Done |
| 2 | Accept requester details on DSR submissions | Yes | In progress |
| 3 | Separate URL issuance from delivery evidence | Yes | Not started |
| 4 | Real invite delivery provider / NoOp guard | Yes | Not started |
| 5 | Retention runner Taskfile and ops docs | Yes | Not started |
| 6 | Runtime secrets and Docker hardening | Yes | Not started |
| 7 | PostgreSQL DSR provider integration tests | Yes | Not started |
| 8 | Streaming DSR export archive generation | Yes | Not started |
| 9 | Authorised representative DSR workflow | Yes | Not started |
| 10 | Final #328 closure reconciliation | Yes | Not started |

## PR-328-2 — Accept requester details on DSR submissions

Priority: P2
Type: `feat(privacy)`
Recommended branch: `feat/privacy-dsr-requester-note`
Recommended PR title: `✨ feat(privacy): accept requester notes on DSR submissions`

### Goal

Expose requester-provided details at the self-service DSR API boundary and make
those details available to authorised platform reviewers without leaking them
into user-facing DSR responses or audit metadata.

### Implementation plan

1. Add optional `requester_note` to `CreateDataSubjectRequest`.
2. Keep `extra="forbid"` on the request schema.
3. Trim `requester_note` at the API schema boundary.
4. Store blank notes as `None`.
5. Enforce a 2000-character request-schema limit.
6. Pass the normalised note into `DataSubjectRequestService.submit_request()`.
7. Keep user-facing `DataSubjectRequestResponse` minimal and do not echo
   `requester_note` back to the requester.
8. Add `requester_note` to platform DSR responses so authorised reviewers can
   evaluate the request.
9. Add API tests for persistence, platform visibility, response minimisation,
   overlong-note rejection and idempotency fingerprint behaviour.
10. Update `backend/docs/privacy-dsr.md` and `backend/docs/current-state.md`.

### Failure cases to cover

- Overlong requester note is rejected and no DSR row is created.
- Blank requester note is normalised to `None`.
- Idempotency key conflict is raised when the same key is reused with a
  different note.
- User-facing response does not include `requester_note`.
- Platform DSR response includes `requester_note` for authorised reviewers.
- Audit metadata remains minimal and does not copy full requester notes.

### Suggested verification

Run from `backend`:

```powershell
task format
uv run --locked ruff check app/privacy/schemas/data_subject_requests.py app/privacy/api/data_subject_requests.py tests/privacy/test_data_subject_request_api.py
uv run --locked ruff format --check app/privacy/schemas/data_subject_requests.py app/privacy/api/data_subject_requests.py tests/privacy/test_data_subject_request_api.py
uv run --locked pytest -q tests/privacy/test_data_subject_request_api.py
uv run --locked pytest -q tests/privacy/test_data_subject_request_service.py
uv run --locked pytest -q tests/privacy/test_dsr_execution_policy.py
uv run --locked pytest -q -m "privacy and not external_db"
uv run --locked pytest -q -m contract
```

## Next work after PR-328-2

PR-328-3 — separate export download URL issuance from delivery evidence.

## Notes for future agents

- Keep PRs small and do not combine unrelated privacy, invite, ops and runtime
  hardening work.
- Documentation can lag code; always verify `main` before changing scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Do not close #328 until every roadmap item is done or explicitly removed from
  #328 scope by a documented decision.
