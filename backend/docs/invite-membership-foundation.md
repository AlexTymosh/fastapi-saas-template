# Invite and membership foundation scope

This branch is a **foundation step** for organisation membership and invitation flows. It is intended to be a safe baseline for the next development iterations, not the final end-to-end invite management system.

## Implemented in this foundation

- Active/inactive membership model for transfer-style membership changes.
- Invite creation baseline with pending invite records.
- Invite acceptance with atomic membership transfer and explicit transaction handling.
- Invite expiration support via `expires_at` and lazy expiration enforcement during accept.
- Soft-delete organisation baseline (`deleted_at`).

## Not fully implemented yet

The following capabilities are intentionally out of scope for this foundation and remain future work:

- Full support/operations workflows around invite recovery.
- Member removal flows.
- Self-leave flows.
- Full owner/admin role mutation flows.
- Comprehensive audit logging for membership and invite lifecycle events.
- Complete organisation deletion/status policy matrix.

## Local role model

- Platform roles are stored in `platform_staff` and drive `/api/v1/platform/*` authorisation.
- Tenant roles are stored in organisation `memberships` and drive `/api/v1/organisations/*` authorisation.
- These role models are intentionally separated and must not be merged in business logic.

## Security and delivery note

Raw invite tokens are generated for out-of-band delivery but are not part of the normal public invite creation API response contract. Invite delivery now uses a transactional outbox: invite/audit/outbox rows are committed together, while delivery runs asynchronously and at-least-once from background workers.

`invites.token_hash` stores `sha256(raw_token)`. The outbox payload stores only `encrypted_raw_token`; plain `raw_token` is never persisted in payload JSON.
Workers decrypt token material in memory only when invite delivery is enabled, verify `sha256(raw_token) == invites.token_hash`, and then deliver. Wrong key/material mismatch is handled as a safe failed attempt.
Outbox workers now use DB-backed status/attempt tracking as the source of truth and do not rely on Dramatiq retries for business delivery retries. A dispatcher actor (`enqueue_pending_outbox_events`) enqueues due pending events for processing.

## Authorisation semantics and invite token test seam

For organisation-scoped foundation endpoints, this branch now applies a single access rule consistently:

1. Load organisation first.
2. Return `404 Not Found` when organisation does not exist (including soft-deleted records).
3. Only then evaluate actor access and return `403 Forbidden` when the organisation exists but actor permissions are insufficient.

This policy is applied to organisation read/membership-list flows and organisation-scoped invite creation.

To keep invite API tests realistic without exposing raw tokens in the public API contract, token delivery is executed only by outbox workers through a token sink abstraction (`InviteTokenSink`). Local/test environments may use an in-memory or NoOp sink. Protected environments must use the SMTP sink when invite delivery is enabled.


## Outbox runtime operations (P0)

Runtime now uses two dedicated background processes:

- Dramatiq worker: `dramatiq app.outbox.worker_runtime`
- Outbox dispatcher: `python -m app.outbox.dispatcher --interval 5 --batch-size 100`

Lifecycle is explicitly split:

1. Request transaction writes invite + audit + outbox event.
2. Dispatcher recovers stale processing events (`processing -> pending/failed`) based on timeout and retry policy.
3. Dispatcher claims due events (`pending -> processing`, sets `locked_at`) and commits.
4. Dispatcher enqueues claimed IDs to Dramatiq.
5. Worker loads claimed event, skips non-pending or expired invites, performs external delivery **outside** DB transaction, then commits result transition.

Status transitions:

- Success: `pending -> processing -> processed`
- Failure with retries remaining: `pending -> processing -> pending`
- Failure with max attempts reached: `pending -> processing -> failed`
- Expired pending invite: invite `pending -> expired`, outbox event `processing -> processed` without delivery
- Disabled delivery: outbox event `processing -> processed` without token decryption or delivery

If enqueue fails after claim commit, dispatcher immediately re-opens a DB transaction and releases that event with retry semantics (`enqueue_failed:*`), so it does not remain stuck in `processing`.
At-least-once delivery remains the contract: duplicate delivery is still possible (for example, worker crash after external delivery but before `mark_processed`). Idempotent downstream delivery is a follow-up hardening task (P1/P2).

Expired pending invites are terminalized before token decryption and SMTP delivery. This prevents a recovered worker from sending dead invite links after a worker outage or SMTP misconfiguration lasts beyond the invite TTL.

When invite delivery is disabled, claimed invite events are marked processed after the invite status/expiry gates and before token decryption. This allows operators to drain pending outbox events without requiring SMTP settings or a valid `SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY` for old encrypted payloads.


## Encryption key requirements

- Invite outbox payload encryption uses Fernet (`SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY`).
- `local` and `test` may use deterministic fallback key when env var is omitted.
- `dev`, `staging`, and `prod` require explicit key when `OUTBOX__INVITE_DELIVERY_ENABLED=true`.
- Disabled invite delivery does not decrypt invite outbox tokens, so workers can drain already-claimed invite events without requiring this key.
- Worker decryption/key mismatch is handled safely: event is failed/retried without exposing raw token or encrypted payload.
- Key rotation and KMS integration are not part of this task.
- Processed-outbox retention/cleanup remains a separate follow-up task.

## Invite delivery provider

Invite delivery is configured with `INVITE_DELIVERY__*` environment variables.

Supported providers:

- `noop`: local/test placeholder only.
- `smtp`: real SMTP delivery provider used by protected environments.

When `OUTBOX__INVITE_DELIVERY_ENABLED=false`, workers process invite outbox events without decrypting invite tokens or creating a delivery sink. This lets operators disable invite delivery without clearing stale SMTP environment variables, without requiring an invite token encryption key for stale payloads, and without sending invite emails.

When `OUTBOX__INVITE_DELIVERY_ENABLED=true`, `dev`, `staging`, and `prod` must not use `INVITE_DELIVERY__PROVIDER=noop`. The worker refuses to create a NoOp sink in those environments, so an unsafe configuration fails the outbox delivery attempt instead of silently marking invite events as delivered.

Required SMTP settings:

- `INVITE_DELIVERY__PROVIDER=smtp`
- `INVITE_DELIVERY__FROM_EMAIL`
- `INVITE_DELIVERY__ACCEPT_URL_TEMPLATE`, containing `{token}`
- `INVITE_DELIVERY__SMTP_HOST`

Optional SMTP settings:

- `INVITE_DELIVERY__SMTP_PORT`, default `587`
- `INVITE_DELIVERY__SMTP_USERNAME`
- `INVITE_DELIVERY__SMTP_PASSWORD`
- `INVITE_DELIVERY__SMTP_TIMEOUT_SECONDS`, default `10.0`
- `INVITE_DELIVERY__SMTP_USE_TLS`, for direct TLS/SMTPS
- `INVITE_DELIVERY__SMTP_START_TLS`, for STARTTLS on plain SMTP

Blank optional SMTP values from copied local env templates are treated as unset. `SMTP_USERNAME` and `SMTP_PASSWORD` must be configured together. Direct TLS and STARTTLS are mutually exclusive.

`staging` and `prod` invitation accept URL templates must use `https://`, and SMTP transport must use either direct TLS (`SMTP_USE_TLS=true`) or STARTTLS (`SMTP_START_TLS=true`). Plain SMTP is rejected in those environments before the worker creates an SMTP sink.

The SMTP sink builds the accept link by URL-encoding the raw token into the configured `{token}` placeholder. Raw tokens remain in memory only: they are decrypted by the worker, validated against `invites.token_hash`, inserted into the outbound email link, and not logged or persisted by the delivery provider.

## SQLite and PostgreSQL compatibility note

- Production-safe path remains PostgreSQL.
- Invite repository update flows use SQL `RETURNING` through SQLAlchemy.
- Invite update statements that compare `expires_at` with runtime timestamps use
  `synchronize_session="fetch"`, so SQLite test runs do not evaluate
  naive/aware datetime comparisons in Python.
- SQLite compatibility for these flows requires SQLite **3.35+** (first version with `RETURNING` support).
