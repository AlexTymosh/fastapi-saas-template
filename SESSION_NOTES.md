# SESSION_NOTES — Layer-boundary remediation

## Current objective

Resolve the seven P1/P2 findings from the layer-boundary audit without a
repository-wide rewrite.

**PR 1 is implemented in the current patch.** Do not implement later PRs in
the same patch. PR 2 becomes the next execution target only after PR 1 is
reviewed, merged, and CI is green.

## Audit posture

- P0: 0.
- P1: 2.
- P2: 5.
- Overall architecture: mixed, but not repository-wide spaghetti.
- Main risk areas: privacy export storage, transaction ownership, privacy
  retention, outbox delivery, and cross-domain dependency direction.
- Code is the source of truth. Revalidate the affected functions before each
  PR because the audit is a point-in-time assessment.

## Findings to close

1. **P1 — Export upload intent is not durable before object storage write.**
   A worker can upload a ZIP and crash before the database records its key.
2. **P1 — Transaction ownership is split between dependencies, routes, and
   services.**
   Service behavior depends on incidental SQLAlchemy transaction state.
3. **P2 — Privacy maintenance duplicates persistence and retention policy.**
   It directly queries and mutates tables owned by other domains.
4. **P2 — The outbox worker contains the invite-delivery use case.**
   It mixes payload validation, invite rules, delivery, and persistence.
5. **P2 — Erasure performs storage I/O from a SQLAlchemy transaction hook.**
   Blocking object deletion is hidden in session lifecycle callbacks.
6. **P2 — InviteService reaches through MembershipService to its repository.**
   Invite authorization depends on another service's implementation detail.
7. **P2 — `app.core.platform` depends on platform and user domains.**
   The dependency direction is reversed and can grow into a circular import.

## Non-negotiable invariants

- Keep the modular-monolith flow:
  `API/dependency -> service -> repository/adapter`.
- Write API dependencies own root transactions.
- CLI commands and workers own their explicit root transactions.
- Application services do not call root `begin()`, `commit()`, or `rollback()`.
- Repositories may `flush()` and `refresh()`, but never commit or roll back.
- Authentication and request-level rate limiting complete before a write
  transaction opens.
- One business write, its audit rows, and its outbox rows commit atomically.
- External storage and email calls do not run inside database transactions.
- Never delete an export object before a committed non-downloadable database
  state exists.
- A failed cleanup keeps a durable retry key.
- Do not promise exactly-once SMTP delivery. SMTP remains at-least-once.
- Do not introduce a new framework or dependency.
- Prefer the existing `export_artifacts.storage_key` as the durable cleanup
  marker. Add a migration only if code-level validation proves it necessary.
- Keep code lines at or below 88 characters.

## Ordered PR plan

| Order | Priority | PR | Finding closed | Risk | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | P1 | Durable export upload intent | 1 | High | Implemented in this patch |
| 2 | P1 | Tenant write-context foundation | 2, part 1 | Medium | Pending |
| 3 | P1 | Organisation/membership transaction migration | 2, part 2 | Medium–High | Pending |
| 4 | P1/P2 | Invite transaction/boundary migration | 2, 6 | Medium–High | Pending |
| 5 | P2 | Repository-owned privacy retention | 3 | Medium | Pending |
| 6 | P2 | Explicit erasure object cleanup | 5 | Medium | Pending |
| 7 | P2 | Invite outbox delivery use case | 4 | Medium | Pending |
| 8 | P2 | Platform access ownership | 7 | Low–Medium | Pending |

The P1 transaction finding is complete only after PRs 2–4 are merged.

---

## PR 1 — Persist export upload intent before object write

**Status:** implemented in this patch; pending review, local container tests,
and CI

**Suggested commit**

```text
🛡️ security(privacy): persist export upload intent

- Record and commit a stable storage key before writing the export archive.
- Preserve failed upload keys for idempotent cleanup and retention retries.
- Cover upload, ready-transition, stale-worker, and purge failure windows.
```

### Scope

- `backend/app/commands/privacy_export_worker.py`
- `backend/app/privacy/services/export_artifacts.py`
- `backend/app/privacy/repositories/export_artifacts.py`
- `backend/app/privacy/export_artifact_lifecycle.py`
- focused export worker, service, retention, and storage tests
- export artifact documentation if behavior changes

### Implementation

1. Keep archive preparation, upload, and ready transition as distinct phases.
2. Before `put_file()`:
   - validate the active processing lease;
   - choose a stable object key for the artifact;
   - persist `storage_backend` and `storage_key`;
   - commit that upload intent.
3. Reuse an existing recorded key on stale recovery or retry. Never replace a
   recorded key with a new random key unless the old object has been durably
   scheduled for purge.
4. Keep `processing` and `failed` artifacts non-downloadable. Download URL
   generation must continue to require `ready`.
5. If upload or ready/audit persistence fails:
   - first commit the artifact as `failed` while retaining `storage_key`;
   - then attempt object deletion outside the transaction;
   - clear storage metadata only in a later transaction after deletion
     succeeds;
   - retain the key when deletion fails.
6. Extend export retention to select failed artifacts that still have a
   storage key. Deletion must be idempotent when the object does not exist.
7. Preserve cleanup priority:
   - subject-erasure cancellation retry;
   - failed generation/upload retry;
   - READY to EXPIRED transition;
   - previously expired object retry.
8. Preserve the existing rule that a rollback cannot restore a downloadable
   row whose object has already been deleted.
9. A failed purge must not prevent unrelated READY artifacts from becoming
   non-downloadable. Preserve the existing rule that a storage error is raised
   only when no useful retention work can complete.

### Acceptance criteria

- Every attempted external object key is recorded before external I/O.
- A crash after upload cannot create an object unknown to the database.
- Stale recovery reuses the recorded key and cannot create a second orphan.
- Ready/audit transaction failure leaves a non-downloadable, purgeable row.
- Cleanup failure leaves the retry key intact.
- One failing cleanup does not starve unrelated expiry work.
- Successful cleanup clears storage and derived file metadata.
- No new table is added unless the current model cannot satisfy an invariant.

### Focused tests

- Upload succeeds and ready/audit persistence fails.
- Worker stops after upload, then stale recovery and retry run.
- Upload fails after the intent is committed.
- Immediate cleanup fails, then retention succeeds.
- Retry uses the same key.
- A missing object can be purged idempotently.
- READY rollback and committed-state retention regressions stay green.

Run from `backend/`:

```powershell
uv run pytest -q tests/privacy/test_export_artifact_service.py
uv run pytest -q tests/privacy/test_privacy_export_worker.py
uv run pytest -q tests/privacy/test_privacy_retention_maintenance.py
uv run pytest -q tests/privacy/test_export_artifact_s3_storage_integration.py
```

### Implementation result

- `storage_key` is now committed before `put_file()` and reused after stale
  recovery.
- The worker revalidates the processing token, lease, backend, and key before
  external I/O.
- Upload and ready/audit failures first commit a non-downloadable `failed` row.
- Immediate cleanup runs outside a database transaction; failed cleanup keeps
  the key for retention.
- Retention cleanup now prioritises subject-erasure retries, failed-upload
  retries, READY expiry, and previously expired retries.
- No migration, table, or dependency was added.
- S3 versioning/noncurrent-version deletion is an explicit production
  deployment requirement in the export and retention documentation.

Verification completed in the implementation environment:

- Ruff format and lint: passed for the complete backend.
- Focused export/worker/retention suite: 63 passed.
- Privacy suite without container/external-DB tests: 437 passed.
- Contract suite: 111 passed.
- Complete lightweight backend suite: 1319 passed.
- Local and mocked S3/storage slice: 36 passed.
- Two MinIO container tests could not start because the environment has no
  Docker socket; run them locally and in CI before merge.

### Separate follow-up discovered during impact analysis

**P2 — Reconcile stale privacy-export temporary archives.**

A hard process/container crash can leave a `privacy-export-*.tmp` archive under
the configured local staging path. This is not an object-storage upload-intent
failure and should not be mixed into PR 1: safe cleanup needs an ownership/age
contract that cannot delete an archive still used by another worker.

Create a separate issue to move staging to an explicitly ephemeral directory
and/or add lease-aware stale temporary-file reconciliation with crash-recovery
tests. This follow-up does not invalidate the durable external upload-intent
fix, but it should be completed before claiming crash-proof local staging.

---

## PR 2 — Add caller-owned tenant write contexts

**Status:** blocked by PR 1

**Suggested commit**

```text
♻️ refactor(db): add tenant write transaction boundary

- Open tenant write transactions after authentication and rate limiting.
- Make user projection and tenant privacy services transaction-agnostic.
- Replace route-owned privacy transactions with dependency-owned contexts.
```

### Scope

- add a tenant write-context module under an application-owned package such as
  `app.access_control`, not under `app.core`
- `backend/app/users/services/users.py`
- `backend/app/users/api/users.py`
- tenant privacy write routes
- invite-specific dependency foundations without migrating InviteService yet
- transaction and rate-limit ordering tests

### Implementation

1. Add a narrow `TenantWriteContext` carrying the request-scoped session and
   authenticated principal. It may also carry a resolved user only when eager
   projection is safe for that endpoint.
2. The dependency order must be:
   - authenticate;
   - run request-level rate limits;
   - open one root transaction;
   - yield the context;
   - commit on success or roll back on failure.
3. Do not eagerly create a user before invite-token validation in the invite
   acceptance flow.
4. Make `UserService` transaction-agnostic:
   - retain nested savepoints used to recover uniqueness races;
   - remove root transaction inference via `in_transaction()`;
   - remove root `begin()` calls.
5. Use an explicit user-projection dependency/use case for read endpoints that
   intentionally synchronise JIT profile data. Do not hide that write inside a
   normal read service method.
6. Replace direct `db_session.begin()` calls in tenant privacy API routes with
   dependency-owned contexts.
7. Preserve route rate-limit metadata used by contract tests.

### Acceptance criteria

- Authentication/rate-limit rejection opens no database transaction.
- Each migrated write request enters exactly one root transaction.
- JIT projection and the privacy mutation roll back together on failure.
- UserService can be composed inside an existing unit of work.
- No migrated route owns a transaction directly.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/services/test_user_service.py
uv run pytest -q tests/privacy/test_data_subject_request_api.py
uv run pytest -q tests/privacy/test_export_artifact_api.py
uv run pytest -q tests/rate_limit/test_api_rate_limiting.py
uv run pytest -q tests/rate_limit/test_endpoint_protection.py
```

---

## PR 3 — Migrate organisation and membership transactions

**Status:** blocked by PR 2

**Suggested commit**

```text
♻️ refactor(tenancy): centralize organisation transactions

- Move organisation and membership writes into caller-owned units of work.
- Keep user projection, domain rows, and audit events atomic.
- Move ordered owner-role persistence into MembershipRepository.
```

### Scope

- organisation API routes
- onboarding, organisation, and membership services
- membership repository
- organisation/membership service and API tests

### Implementation

1. Route every organisation and membership write through the tenant
   write-context dependency.
2. Remove service-owned root transactions and `in_transaction()` branching
   from:
   - `OnboardingService`;
   - `OrganisationService`;
   - `MembershipService`.
3. Keep business rules and authorization decisions in services.
4. Move the ordered owner swap persistence into a narrow repository method:
   - lock active memberships;
   - demote the current owner;
   - flush when required by the uniqueness constraint;
   - promote the replacement;
   - flush;
   - let the service verify the one-owner invariant.
5. Do not move role eligibility or authorization decisions into the repository.
6. Ensure JIT user projection, organisation/membership changes, and audit
   events share one transaction.

### Acceptance criteria

- Services work after a prior read without relying on `in_transaction()`.
- Services are callable inside a larger unit of work.
- A forced audit failure rolls back projection and domain changes.
- Owner replacement preserves exactly one active owner.
- Concurrent owner replacement cannot commit two active owners.
- No service directly flushes owner role changes.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/services/test_organisation_service.py
uv run pytest -q tests/services/test_membership_service.py
uv run pytest -q tests/organisations
uv run pytest -q tests/rate_limit/test_tenant_write_business_rate_limits.py
```

---

## PR 4 — Migrate invites and close service reach-through

**Status:** blocked by PR 3

**Suggested commit**

```text
♻️ refactor(invites): enforce public service boundaries

- Run invite workflows inside caller-owned write transactions.
- Resolve actor membership through a public MembershipService method.
- Preserve atomic invite, audit, and outbox writes.
```

### Scope

- invite API dependencies and routes
- `InviteService`
- `MembershipService`
- invite, membership, rate-limit, and outbox publication tests
- final transaction architecture contract test

### Implementation

1. Add a narrow public membership method such as
   `require_active_membership()`.
2. Make `InviteService._get_actor_membership()` call that public method.
   Remove access to `membership_service.membership_repository`.
3. Remove all root `begin()`, `in_transaction()` branching, and
   `_NoopContext` from InviteService.
4. Let invite API yield dependencies own one root transaction while preserving:
   - actor/token rate limits before the transaction;
   - tenant business-scope rate limits only after authorization;
   - invite expiry rechecks after awaited rate-limit calls.
5. Keep invite creation/resend, audit rows, and outbox publication atomic.
6. In invite acceptance, validate the token/email before creating a local user,
   but keep both actions in the same transaction.
7. Add a static contract test:
   - application services contain no root `begin`, `commit`, or `rollback`;
   - API route modules contain no direct transaction boundary;
   - `begin_nested()` remains allowed for documented savepoints;
   - dependencies, CLI commands, and workers remain allowed owners.

### Acceptance criteria

- InviteService no longer depends on another service's repository attribute.
- Missing/inactive membership behavior is unchanged.
- The owner/admin/member authorization matrix is unchanged.
- InviteService is composable inside an existing unit of work.
- A forced audit/outbox failure rolls back the invite and JIT projection.
- Exactly one root transaction exists per invite write request.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/invites
uv run pytest -q tests/services/test_invite_service.py
uv run pytest -q tests/services/test_membership_service.py
uv run pytest -q tests/outbox/test_outbox_payloads.py
uv run pytest -q tests/rate_limit/test_invite_rate_limit_contexts.py
uv run pytest -q tests/rate_limit/test_tenant_write_business_rate_limits.py
```

---

## PR 5 — Move privacy retention persistence to owning domains

**Status:** blocked by PR 4

**Suggested commit**

```text
♻️ refactor(privacy): route retention through repositories

- Keep privacy maintenance as cross-domain orchestration only.
- Consolidate invite, outbox, audit, and DSR retention policies.
- Preserve dry-run, legal-hold, batching, and idempotency behavior.
```

### Scope

- `backend/app/privacy/maintenance.py`
- invite, outbox, audit, and DSR services/repositories
- retention tests and operator documentation

### Implementation

1. Keep `run_privacy_retention_maintenance()` as the cross-domain
   orchestration entry point.
2. Move each table's selection and mutation to its owning repository.
3. Expose narrow service/repository operations for:
   - completed invite anonymisation;
   - terminal outbox payload scrubbing;
   - audit minimisation with legal-hold recheck;
   - expired DSR idempotency-key cleanup.
4. Consolidate duplicate field lists, tombstones, cutoffs, and marker rules.
   Each table must have one canonical retention policy.
5. Keep already-scrubbed rows out of capped candidate batches.
6. Preserve dry-run as a true preview:
   - no ORM mutation;
   - no flush;
   - no storage call.
7. Keep the audit UPDATE eligibility predicates in the final mutation so a
   legal hold added after selection still wins.
8. Add a contract test that orchestration-only maintenance modules do not
   construct SQLAlchemy `select`, `update`, or `delete` statements.

### Acceptance criteria

- `privacy/maintenance.py` contains no aggregate SQL or direct ORM mutation.
- All entry points use identical field and cutoff policies.
- A legal-hold race cannot minimise a protected event.
- Repeated bounded runs cannot starve unsanitized rows.
- Dry-run is non-mutating.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/privacy/test_privacy_retention_maintenance.py
uv run pytest -q tests/invites/test_invite_retention.py
uv run pytest -q tests/audit/test_audit_retention_maintenance.py
uv run pytest -q tests/outbox
```

---

## PR 6 — Make erasure object cleanup explicit

**Status:** blocked by PR 5

**Suggested commit**

```text
♻️ refactor(privacy): make export cleanup explicit

- Remove storage I/O from SQLAlchemy transaction event hooks.
- Reuse one export storage adapter resolver across privacy workflows.
- Let committed non-downloadable rows drive retryable retention cleanup.
```

### Scope

- `backend/app/privacy/erasures/remaining_inventory.py`
- export artifact service and storage package
- retention/erasure tests
- privacy export and erasure operations documentation

### Implementation

1. Remove storage deletion from SQLAlchemy transaction event listeners.
2. During erasure, only:
   - mark subject-owned artifacts non-downloadable;
   - clear subject metadata;
   - retain storage backend/key as the durable cleanup marker.
3. Let the retention runner purge committed cancelled rows. Document the
   expected cleanup cadence/SLA.
4. If immediate cleanup later becomes mandatory, enqueue an explicit
   post-commit job. Do not restore hidden ORM hooks.
5. Create one storage resolver/factory under `app.privacy.storage`.
6. Reuse it from export generation, retention, and erasure-related paths.
7. Preserve rollback behavior: a rolled-back erasure never deletes an object.

### Acceptance criteria

- Completing an API erasure performs no storage call on the request thread.
- Commit leaves a non-downloadable row with a retry key.
- Rollback leaves the READY row and object untouched.
- The next retention pass deletes the object and clears metadata.
- Storage failure retains the key for another pass.
- Every privacy path resolves identical adapter configuration.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/privacy/test_erasure_orchestrator.py
uv run pytest -q tests/privacy/test_platform_erasure_execution_api.py
uv run pytest -q tests/privacy/test_privacy_retention_maintenance.py
uv run pytest -q tests/privacy/test_export_artifact_s3_storage_integration.py
```

---

## PR 7 — Extract the invite outbox delivery use case

**Status:** blocked by PR 6

**Suggested commit**

```text
♻️ refactor(outbox): extract invite delivery workflow

- Move invite-delivery decisions from the worker into an application service.
- Load invites through InviteRepository and use a stable delivery identifier.
- Keep SMTP at-least-once behavior explicit and observable.
```

### Scope

- outbox worker and a new narrow invite-delivery application service
- outbox and invite repositories
- invite delivery sink protocol and SMTP implementation
- outbox worker tests and delivery documentation

### Implementation

1. Keep the Dramatiq actor thin:
   - parse the event ID;
   - own the worker transaction phases;
   - delegate business decisions to the application service.
2. Move payload validation, invite state/expiry checks, token validation,
   provider selection, and outcome mapping into the service.
3. Replace the worker's direct `select(Invite)` with `InviteRepository`.
4. Keep external delivery outside a database transaction.
5. Derive a stable delivery ID from `outbox_event.id` and pass it through the
   sink interface on every retry.
6. Use the stable ID as a provider idempotency key when supported.
7. For SMTP, use a stable message identifier/header for traceability, but
   document that it does not guarantee provider deduplication.
8. Log/measure retry-after-possible-delivery without logging email addresses,
   tokens, or payload secrets.

### Acceptance criteria

- Worker code contains no invite SQL or invite business rules.
- Every retry uses the same delivery ID.
- Concurrent duplicate jobs still produce only one active delivery claim.
- Delivery success followed by acknowledgement failure has explicit,
  observable retry behavior.
- Documentation continues to state at-least-once SMTP semantics.

### Residual risk

The send/ack crash window cannot be eliminated with generic SMTP. True
provider-level deduplication requires a delivery provider that accepts an
idempotency key. This is an explicit transport limitation, not a reason to
claim exactly-once behavior.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/outbox/test_outbox_workers.py
uv run pytest -q tests/outbox/test_outbox_worker_idempotency.py
uv run pytest -q tests/outbox/test_expired_invite_delivery.py
uv run pytest -q tests/invites/test_invite_delivery.py
```

---

## PR 8 — Move platform access code out of core

**Status:** blocked by PR 7

**Suggested commit**

```text
♻️ refactor(platform): move access control out of core

- Move platform actors, permissions, and dependencies under platform ownership.
- Remove reversed core-to-domain imports and update public import paths.
- Add an architecture contract for allowed core dependencies.
```

### Scope

- move `app.core.platform` to a platform-owned package such as
  `app.platform.access`
- update application and test imports
- delete obsolete compatibility re-exports after migration
- add import-boundary contract tests

### Implementation

1. Move actor, permission matrix, read dependencies, and write contexts under
   `app.platform`.
2. Update platform services, platform APIs, privacy platform APIs, schemas, and
   tests to use the platform-owned public path.
3. Remove `app.core.platform` after all imports are migrated.
4. Add a static import contract:
   - `app.core` cannot import domain packages;
   - only the documented SQLAlchemy model registries are exempt.
5. Add fresh-interpreter import tests for platform services and dependencies.
6. Do not change permission values, role matrices, API behavior, or rate-limit
   metadata.

### Acceptance criteria

- `app.core` no longer imports platform/user implementation code outside the
  documented model registry exception.
- Platform access imports do not form a runtime cycle.
- Permission and rate-limit behavior is unchanged.
- Platform modules import successfully in a fresh interpreter.

### Focused tests

Run from `backend/`:

```powershell
uv run pytest -q tests/platform
uv run pytest -q tests/contracts/test_privacy_docs_contract.py
uv run pytest -q tests/contracts/test_platform_access_docs_contract.py
uv run pytest -q tests/contracts/test_openapi_platform_contract.py
```

## Final verification after PR 8

Run from `backend/`:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest -q -m "not external_db"
```

Then run from the repository root:

```powershell
task ci
```

Final static checks:

```powershell
rg -n "\.begin\(|\.commit\(|\.rollback\(" app --glob "**/services/*.py"
rg -n "session\.execute|\bselect\(|\bupdate\(|\bdelete\(" app/privacy/maintenance.py
rg -n "membership_service\.membership_repository" app
rg -n "app\.core\.platform" app tests
```

Expected result: no unapproved matches. `begin_nested()` savepoints and explicit
CLI/worker/dependency transaction boundaries remain valid exceptions.

## Completion checklist

- [x] PR 1: durable export upload intent implemented; merge/CI pending.
- [ ] PR 2: tenant write-context foundation.
- [ ] PR 3: organisation/membership transaction migration.
- [ ] PR 4: invite transaction and public membership boundary migration.
- [ ] P1 transaction finding re-audited and closed.
- [ ] PR 5: repository-owned privacy retention.
- [ ] PR 6: explicit erasure object cleanup.
- [ ] PR 7: invite outbox delivery use case.
- [ ] PR 8: platform access ownership.
- [ ] Layer-boundary static audit rerun.
- [ ] Full non-external test suite and `task ci` green.
- [ ] Architecture/current-state/operations docs reconciled.

## Required legacy #328 docs-contract anchors

These strings are compatibility anchors for the current documentation contract.
They are not the status of this remediation plan.

- `PR #441 is merged into main.`
- `10F | Final #328 closure reconciliation | Yes | Done`
- `PR-328-10F is done in this patch`
- `Status: Ready after this PR and a green task ci run.`
- Keep `versioned export payload schema contract` tracked in canonical docs.
