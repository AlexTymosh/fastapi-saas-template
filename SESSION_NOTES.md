# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-07-09
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
- PR #437 is merged into `main`.
- PR-328-10A is done: retention maintenance covers export artifacts, invite
  lifecycle rows, delivered/failed outbox payloads, old audit context and
  expired DSR idempotency metadata.
- PR #438 is open for PR-328-10B. Codex review follow-up is prepared for active
  export lease false positives, aggregate database read ownership, CLI
  observability initialization, current failed artifact scoping, atomic gauge
  updates, failed metric status preservation, cancelled work exclusion, expired
  ready artifact degradation and stale artifact metric status preservation.
- PR-328-10C is done in this patch: legacy generic GDPR permissions were removed
  from the runtime platform permission contract and current docs.
- PR-328-10D is done in this patch: provider keys, inventory, runtime export
  providers, provider registry, erasure coverage and the actual erasure
  provider result order are covered by one alignment contract.

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

## PR-328-10B — DSR operations visibility

Priority: P1
Type: `feat(privacy)`
Recommended branch: `privacy/dsr-ops-visibility`
Recommended PR title: `✨ feat(privacy): add DSR execution health visibility`
Status: Open in PR #438; Codex review follow-up patch prepared.

### Delivered scope

1. Added `get_privacy_dsr_execution_health()` for aggregate DSR execution health.
2. Counted `export` and `erase` DSR jobs by execution status.
3. Reported failed and stale queued/processing DSR jobs.
4. Reported export artifact counts, current failed artifacts, undelivered
   expired ready artifacts and stale queued/processing artifacts.
5. Added low-cardinality OpenTelemetry metrics for DSR health snapshots.
6. Added structured health logs without request IDs, user IDs, emails, storage
   keys, tokens, notes or free-form error details.
7. Added `app.commands.privacy_dsr_health` and `task privacy:dsr-health` for
   operator checks.
8. Added Windows-compatible selector-loop CLI execution for Psycopg async.
9. Added `docs/privacy-dsr-operations.md` with command, metrics and log guidance.
10. Added regression tests for degraded/healthy snapshots, metric attributes,
    stale-threshold validation and Windows CLI loop selection.
11. Initialized and shut down the observability provider around CLI health
    snapshots so OTLP metrics can be exported outside the FastAPI lifespan.
12. Added atomic DSR gauge point swaps and failed-signal metric status
    preservation for `failed` and `partially_fulfilled` DSR states.
13. Excluded cancelled DSR requests and artifacts linked only to cancelled DSRs
    from failed/stale degraded signals.
14. Preserved export artifact status in stale metrics for `queued`, `processing`
    and expired `ready` artifacts.
15. Added an explicit CLI transaction boundary around the DSR health snapshot.

### Regression boundaries

- Health snapshots are read-only and do not mutate DSR or export artifact rows.
- Metrics use bounded attributes only: job kind, request type, execution status,
  signal and health status.
- Logs expose aggregate counts only and do not include per-subject identifiers.
- The default stale threshold is one hour and can be overridden per command run.
- Windows CLI execution uses a selector loop because Psycopg async does not
  support the default Proactor loop.
- Actively leased processing export artifacts prevent their linked export DSRs
  from being counted as stale.
- Aggregate SQL reads live in `DsrExecutionHealthRepository`; the service layer
  only orchestrates repository calls, logging and metric emission.
- The standalone CLI initializes observability before recording DSR metrics and
  shuts it down afterwards, including the provider flush path.
- CLI observability shutdown still runs if the snapshot read fails after
  successful observability initialization.
- Superseded historical failed export artifacts remain visible in by-status
  counts but no longer degrade the current health snapshot.
- Observable DSR gauge callbacks read a locked point snapshot while health
  recording swaps in a complete replacement map.
- Failed-signal DSR metric points preserve the underlying execution status;
  `partially_fulfilled` is not relabelled as `failed`.
- Cancelled DSR work is excluded from current, failed and stale DSR signals.
- Export artifacts linked only to cancelled DSRs remain visible in by-status
  counts but do not degrade failed/stale health signals.
- Current undelivered ready export artifacts with `expires_at <= checked_at`
  degrade health.
- Superseded expired ready artifacts remain visible in by-status counts but do
  not degrade the current health snapshot.
- Delivered ready artifacts remain fulfilled history after expiry and do not
  degrade the current health snapshot.
- Stale export artifact metrics preserve `queued`, `processing` and `ready`
  execution statuses instead of collapsing stale rows under `processing`.
- The standalone CLI owns an explicit transaction around the health snapshot and
  exits the transaction before closing the session.

### Codex review follow-up

1. Fixed false degraded snapshots for long-running exports with active future
   processing leases.
2. Moved DSR/export artifact aggregate SQL reads out of the service layer into a
   dedicated privacy read-model repository.
3. Added regression coverage for active export leases and service/repository
   boundary protection.
4. Updated operator docs to describe active lease handling and read-model query
   ownership.
5. Fixed standalone CLI metrics export by initializing observability before the
   DSR health snapshot and shutting it down afterwards.
6. Added regression coverage for CLI observability lifecycle order and failure
   cleanup.
7. Limited failed-artifact degradation to current failed artifacts that have not
   been superseded by a newer artifact for the same DSR.
8. Added regression coverage for superseded failed artifacts and current failed
   artifact degradation.
9. Made DSR observable gauge state updates atomic by building a complete
   replacement map and reading gauge callbacks from a locked snapshot.
10. Preserved `failed` and `partially_fulfilled` execution statuses in
    failed-signal DSR metrics instead of aggregating both as `failed`.
11. Excluded cancelled DSR requests and linked export artifacts from failed/stale
    degraded health signals.
12. Added regression coverage for cancelled DSR work with stale and failed
    artifact history.
13. Added degraded health coverage for current expired ready export artifacts.
14. Preserved queued/processing/ready artifact status in stale metric points.
15. Added an explicit `session.begin()` boundary around the CLI health snapshot.
16. Added regression coverage for CLI transaction commit and rollback paths.
17. Excluded delivered ready artifacts from expired-artifact degraded health
    after download confirmation.
18. Added regression coverage for delivered ready artifacts after expiry.

## PR-328-10C — DSR permission contract cleanup

Priority: P1
Type: `security(privacy)`
Recommended branch: `privacy/dsr-permission-contract-cleanup`
Recommended PR title: `🛡️ security(privacy): remove legacy GDPR permissions`
Status: Done in this patch.

### Delivered scope

1. Removed legacy generic GDPR permission values from `PlatformPermission`.
2. Added `privacy_export_artifacts:manage` as the dedicated platform boundary for
   export artifact creation, platform download URL generation and delivery
   confirmation.
3. Kept approved erase execution on the existing
   `privacy_requests:execute_erasure` boundary.
4. Updated compliance-officer role mapping to include the new export artifact
   management permission and no generic GDPR permissions.
5. Updated platform privacy routes to use the dedicated export artifact manage
   permission for mutating export artifact operations.
6. Updated current DSR and platform access docs to match the runtime permission
   contract.
7. Added regression tests proving the legacy GDPR values are absent from the
   runtime permission enum, docs and export-artifact route dependencies.

### Regression boundaries

- Support agents still cannot read, manage or execute privacy DSR operations.
- Compliance officers can still read/review DSRs, manage export artifacts and
  execute approved erasure through explicit privacy boundaries.
- Platform admins keep all current platform permissions via `ALL_PERMISSIONS`.
- Legacy generic GDPR permission values are not part of the runtime permission
  enum, so they cannot be granted through role mappings.
- Export artifact read routes still require the read-specific permission.
- Export artifact mutating routes use the manage-specific permission and do not
  reuse the read boundary.

## PR-328-10D — Provider contract alignment

Priority: P1
Type: `test(privacy)`
Recommended branch: `privacy/dsr-provider-registry-alignment`
Recommended PR title: `🧹 chore(privacy): align DSR provider registries`
Status: Done in this patch.

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
- Erasure coverage must stay aligned with the central erasure provider
  catalogue.
- The actual `_run_core_providers()` emitted provider result order must match
  the central erasure provider order; wrapper-only order checks are not enough.

## Final #328 closure reconciliation

Status: Not ready. Continue with PR-328-10E through PR-328-10F.

### Remaining scope

1. Remove high-cardinality eager `.all()` loading from subject export providers.
2. Re-run full CI.
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
