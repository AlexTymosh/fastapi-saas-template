# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-07-01
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
- PR #428 is merged into `main`.
- PR-328-3 is done: URL issuance is separated from confirmed delivery evidence;
  delivery confirmation is explicit, rate-limited, atomic, idempotent and guarded
  by artifact availability plus linked DSR eligibility.
- PR #429 is merged into `main`.
- PR-328-4 is done: invite delivery has an SMTP provider, NoOp guardrails for
  protected environments, accept URL validation, and SMTP transport guardrails.
- PR #430 is merged into `main`.
- PR-328-5 is done: retention runner Taskfile commands, CLI smoke tests,
  `.env.example` guardrails and scheduler docs are merged.
- PR #431 is merged into `main`.
- PR-328-6 is done: backend container runtime uses an unprivileged user, runtime
  secret handling is documented, and regression tests guard Docker hardening.
- PR #432 is merged into `main`.
- PR-328-7 is done: PostgreSQL/Testcontainers coverage verifies DSR provider
  JSON predicates used by subject export, erasure impact preview and outbox
  erasure scrubbing.

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
| 9 | Authorised representative DSR workflow | Yes | Not started |
| 10 | Final #328 closure reconciliation | Yes | Not started |

## PR-328-3 — Separate URL issuance from delivery evidence

Priority: P2
Type: `feat(privacy)`
Branch: `feat/privacy-export-delivery-evidence`
PR title: `✨ feat(privacy): separate export URL issuance from delivery evidence`
Status: Done in merged PR #428.

### Delivered scope

1. Added export artifact URL-issuance metadata:
   - `download_url_issued_at`;
   - `download_url_issue_count`.
2. Kept `downloaded_at` and `download_count` for confirmed delivery only.
3. Stopped marking export DSR execution as `delivered` during URL creation.
4. Added self-service and platform `confirm-delivery` endpoints.
5. Marked export DSR execution as `delivered` only after delivery confirmation.
6. Added delivery confirmation audit evidence.
7. Backfilled legacy URL issuance data out of delivery columns.
8. Reclassified legacy ready, expired and cancelled URL-issued DSR states.
9. Guarded delivery confirmation with artifact availability and linked DSR
   eligibility inside the atomic update.
10. Updated API/service/repository/exporter/migration tests and docs.

### Failure cases covered

- URL issued but delivery not confirmed keeps DSR execution state non-delivered.
- Delivery confirmation marks DSR execution as delivered.
- Expired artifacts cannot be confirmed as delivered.
- Another user cannot confirm delivery for someone else's export artifact.
- Multiple URL issuances increase URL issue metadata without increasing delivery
  count.
- Existing download URL rate limits apply to URL issuance and delivery
  confirmation endpoints.
- Repeated/concurrent delivery confirmation remains idempotent.
- Retention, subject-erasure cancellation and platform DSR cancellation races
  cannot write confirmed delivery evidence.

## PR-328-4 — Real invite delivery provider / NoOp guard

Priority: P2
Type: `feat(invites)`
Recommended branch: `feat/invite-delivery-provider-guard`
Recommended PR title: `✨ feat(invites): add SMTP invite delivery provider guard`
Status: Done in merged PR #429; re-verified after merge.

### Goal

The invite outbox worker must not silently mark invite events processed through a
NoOp sink in protected environments. Local/test can still use NoOp for developer
and test workflows, but `dev`, `staging` and `prod` must use a real delivery
provider when invite delivery is enabled.

### Planned implementation

1. Add an SMTP-backed `InviteTokenSink` using Python stdlib email/SMTP support.
2. Keep `NoOpInviteTokenSink` only for local/test or disabled invite delivery.
3. Add `INVITE_DELIVERY__*` settings for provider, sender, accept URL template
   and SMTP connection/auth/TLS controls.
4. Reject NoOp invite delivery in `dev`, `staging` and `prod` when
   `OUTBOX__INVITE_DELIVERY_ENABLED=true`.
5. Require HTTPS invitation accept URLs in `staging` and `prod`.
6. Keep raw invite tokens in memory only and deliver them through the outbox
   worker sink boundary.
7. Add unit/regression tests for provider selection, protected-environment guard,
   SMTP message construction and token URL encoding.
8. Update `.env.example` and invite delivery documentation.

### PR #429 follow-up

Codex found several edge cases after the first implementation. The merged PR now
honours disabled invite delivery before provider selection, tolerates blank local
NoOp SMTP fields, rejects plaintext SMTP in protected environments, terminalizes
expired pending invites before delivery, and short-circuits disabled delivery
before token decryption.

### Failure cases covered

- Protected environment + enabled invite delivery + NoOp provider is rejected.
- Disabled invite delivery + stale SMTP provider settings returns NoOp before
  SMTP configuration is parsed.
- Disabled invite delivery drains pending invite outbox events before token
  decryption and without requiring `SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY`.
- NoOp invite delivery tolerates blank optional SMTP env values copied from the
  local `.env.example` template.
- Expired pending invites are marked expired before token decryption or SMTP
  delivery, and their outbox events are terminally processed without sending.
- SMTP provider cannot start without host, sender and `{token}` URL template.
- SMTP username/password must be configured together.
- Staging/prod accept URL templates must use HTTPS.
- Staging/prod SMTP delivery must use direct TLS or STARTTLS.
- SMTP delivery exceptions continue to bubble to the outbox worker so the outbox
  event is retried/failed instead of marked processed.

## PR-328-5 — Retention runner Taskfile and ops docs

Priority: P2
Type: `chore(privacy)`
Recommended branch: `chore/privacy-retention-runner-ops`
Recommended PR title: `🧹 chore(privacy): add export retention runner ops commands`
Status: Done in merged PR #430; re-verified after merge.

### Delivered scope

1. Added Taskfile commands for retention one-shot and dry-run execution.
2. Added smoke coverage for retention CLI parsing and Taskfile task presence.
3. Documented manual execution and scheduled operation patterns.
4. Documented single-active-runner guidance for scheduled retention jobs.
5. Kept runtime retention behaviour unchanged.
6. Restored auth, outbox and invite delivery examples in `.env.example` after
   Codex found they were accidentally removed.

### Failure cases covered

- Dry-run stays non-mutating.
- Invalid batch size fails clearly.
- Taskfile exposes the intended retention commands from the repository root.
- Scheduled-operation docs do not imply multiple active retention runners are
  safe without a separate distributed lock or row-claiming contract.
- Required runtime auth/outbox/invite env examples are not silently dropped from
  `.env.example`.

## PR-328-6 — Runtime secrets and Docker hardening

Priority: P2
Type: `security(runtime)`
Recommended branch: `security/runtime-secrets-docker-hardening`
Recommended PR title: `🛡️ security(runtime): harden backend container runtime`
Status: Done in merged PR #431; re-verified after merge.

### Delivered scope

1. Added an unprivileged `app:app` runtime user to the backend Docker image.
2. Moved the final backend runtime stage to `USER app:app`.
3. Copied runtime application files with `app:app` ownership.
4. Documented runtime secret handling and container hardening guidance.
5. Updated current-state documentation to avoid overclaiming production readiness.
6. Added regression tests for Dockerfile runtime hardening guardrails.

### Follow-up outside this PR

Remaining string-based secret-like settings should be converted to `SecretStr` in
a separate focused PR if stricter redaction of full settings dumps is required.
Do not combine that refactor with the PostgreSQL DSR provider tests.

## PR-328-7 — PostgreSQL DSR provider integration tests

Priority: P2
Type: `chore(privacy)`
Recommended branch: `test/privacy-postgres-provider-coverage`
Recommended PR title: `🧹 chore(privacy): cover DSR providers on PostgreSQL`
Status: Done in merged PR #432; re-verified after merge.

### Delivered scope

1. Added PostgreSQL/Testcontainers coverage for subject export provider lookup via
   `outbox_events.payload_json["email"]`.
2. Added PostgreSQL/Testcontainers coverage for erasure impact preview counts that
   depend on the same outbox JSON email predicate.
3. Added PostgreSQL/Testcontainers coverage for outbox erasure scrubbing through
   the PostgreSQL JSON predicate and `SELECT ... FOR UPDATE` path.
4. Kept the tests opt-in by infrastructure marker: `privacy`, `integration` and
   `container`; they are not marked `external_db` because they start a disposable
   PostgreSQL container.
5. Updated DSR provider/current-state docs to mark PostgreSQL JSON predicate
   coverage as implemented.

### Failure cases covered

- PostgreSQL JSON predicate finds the subject-linked outbox event.
- PostgreSQL JSON predicate does not include unrelated outbox events.
- Exported outbox references do not expose raw email or encrypted token payloads.
- Erasure impact counts subject-linked outbox events through PostgreSQL JSON
  access.
- Outbox erasure scrubs only the subject-linked JSON payload row.

## PR-328-8 — Streaming DSR export archive generation

Priority: P2
Type: `perf(privacy)`
Recommended branch: `perf/privacy-streaming-export-archives`
Recommended PR title: `⚡️ perf(privacy): stream DSR export archive generation`
Status: Patch prepared; not merged.

### Prepared scope

1. Add a streaming subject export JSON chunk writer that iterates provider records
   without materialising the complete export payload as a Python dictionary for
   archive generation.
2. Replace in-memory ZIP assembly with a temporary ZIP file written through
   `ZipFile.open("export.json", mode="w")`.
3. Add `StorageAdapter.put_file()` and implement file streaming for local and
   S3-compatible storage backends.
4. Compute archive size and checksum by reading the temporary file in bounded
   chunks.
5. Delete temporary archive files after upload and after generation failures.
6. Preserve the existing ZIP schema, storage metadata, DSR execution state and
   public API behaviour.
7. Update export artifact documentation and current-state notes.

### Failure cases to cover

- Archive generation uses streaming JSON chunks and still produces a valid
  `export.json` ZIP member.
- Prepared archive files are deleted after successful storage upload.
- Oversized generated archives fail with `artifact_too_large` and do not leave
  temporary files behind.
- Existing export artifact service behaviour still marks artifacts ready, keeps
  schema fields intact and preserves failure-state synchronisation.

## Notes for future agents

- Keep PRs small and do not combine unrelated privacy, invite, ops and runtime
  hardening work.
- Documentation can lag code; always verify `main` before changing scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Do not close #328 until every roadmap item is done or explicitly removed from
  #328 scope by a documented decision.
