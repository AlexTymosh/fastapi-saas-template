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
- PR #428 is merged into `main`.
- PR-328-3 is done: URL issuance is separated from confirmed delivery evidence;
  delivery confirmation is explicit, rate-limited, atomic, idempotent and guarded
  by artifact availability plus linked DSR eligibility.
- PR #429 is merged into `main`.
- PR-328-4 is done: invite delivery has an SMTP provider, NoOp guardrails for
  protected environments, accept URL validation, and SMTP transport guardrails.

## Roadmap status

| Order | PR | Blocks #328 closure | Status |
|---:|---|---:|---|
| 1 | Define execution policy for non-export DSR types | Yes | Done |
| 2 | Accept requester details on DSR submissions | Yes | Done |
| 3 | Separate URL issuance from delivery evidence | Yes | Done |
| 4 | Real invite delivery provider / NoOp guard | Yes | Done |
| 5 | Retention runner Taskfile and ops docs | Yes | Patch prepared |
| 6 | Runtime secrets and Docker hardening | Yes | Not started |
| 7 | PostgreSQL DSR provider integration tests | Yes | Not started |
| 8 | Streaming DSR export archive generation | Yes | Not started |
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

Codex found that `OUTBOX__INVITE_DELIVERY_ENABLED=false` was not honoured before
SMTP provider selection. The fix short-circuits `get_invite_token_sink()` to the
NoOp sink before parsing `INVITE_DELIVERY__*` provider settings when invite
delivery is disabled. This prevents disabled workers from sending SMTP invites
or failing on stale SMTP configuration.

Codex also found that blank `INVITE_DELIVERY__FROM_EMAIL=` values from copied
local/test env templates failed `EmailStr` validation before NoOp delivery could
be selected. The fix normalises blank sender values to `None` before validation,
while preserving `FROM_EMAIL` as required for SMTP delivery.

Codex also found that `staging`/`prod` SMTP delivery could be configured with
both direct TLS and STARTTLS disabled. The fix rejects plaintext SMTP transport
in those environments before returning an SMTP sink.

Codex also found that a recovered outbox worker could still send SMTP delivery
for a pending invite after `expires_at` had passed. The fix terminalizes expired
pending invites before token decryption and SMTP delivery, then marks the outbox
event processed without sending a dead invite link.

Local regression tests found SQLAlchemy's default ORM session evaluation could
compare SQLite naive datetimes with UTC-aware decision timestamps in invite
expiry bulk updates. The fix sets `synchronize_session="fetch"` on invite update
statements that compare `expires_at` with runtime timestamps, so the database
performs the comparison and the session is synchronized through returned rows.

Codex also found that disabled invite delivery still happened after token
decryption in the worker. The fix now short-circuits disabled delivery after the
invite status/expiry gates and before `OutboxPayloadCrypto` is constructed, so
disabled workers can drain events without SMTP, without token decryption and
without requiring a configured outbox token encryption key for stale payloads.

### Failure cases to cover

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
Status: Patch prepared; not merged.

### Prepared scope

1. Add Taskfile commands for retention one-shot and dry-run execution.
2. Add smoke coverage for retention CLI parsing and Taskfile task presence.
3. Document manual execution and scheduled operation patterns.
4. Keep runtime retention behaviour unchanged.

### Failure cases to cover

- Dry-run stays non-mutating.
- Invalid batch size fails clearly.
- Taskfile exposes the intended retention commands from the repository root.
- Scheduled-operation docs do not imply multiple active retention runners are
  safe without a separate distributed lock or row-claiming contract.

## Notes for future agents

- Keep PRs small and do not combine unrelated privacy, invite, ops and runtime
  hardening work.
- Documentation can lag code; always verify `main` before changing scope.
- Use backend-relative pytest paths when commands start from the `backend`
  directory.
- Keep code lines within 88 characters.
- Do not close #328 until every roadmap item is done or explicitly removed from
  #328 scope by a documented decision.
