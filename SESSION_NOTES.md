# SESSION_NOTES — Issue #328 full-closure plan

Date: 2026-06-27
Repository: `AlexTymosh/fastapi-saas-template`
Branch used for verification: `main`
Parent issue: `#328 — P1: No implemented Data Subject Rights workflow despite GDPR permissions existing`

## Current decision

Do **not** close #328 yet.

The backend DSR foundation, export workflow, erasure execution, privacy routers,
inventory-aligned erasure coverage and contract tests are implemented. Tests are
green according to the latest local verification.

However, #328 should stay open until all currently known privacy/DSR-related P2
follow-up issues are resolved, because the project owner wants full closure, not
only backend-foundation closure.

## Current state summary

| Area | Status | Notes |
|---|---:|---|
| Dedicated privacy/DSR module | Done | Implemented under `backend/app/privacy`. |
| Privacy routers in master router | Done | Self-service DSR, platform DSR, self-service export artifacts and platform export artifacts are registered. |
| DataSubjectRequest model/lifecycle | Done | Request type, requester, subject, reviewer, status, timestamps, execution status and reason fields exist. |
| Self-service DSR API | Done | Submit/list/get/cancel flow exists. |
| Platform DSR API | Done | Review/approve/reject/cancel/execute-erasure/fulfil flow exists. |
| Export artifact workflow | Done | Queued artifacts, worker path, download URL generation, retention runner and S3-compatible storage exist. |
| Erasure execution | Done | Platform execute-erasure endpoint calls the service/orchestrator boundary. |
| Inventory-aligned erasure coverage | Done | Coverage map, provider order and contract tests exist. |
| Final closure review issue #409 | Done | Closed as completed. |
| `task ci` | Done | User reported tests are green. |
| Full #328 closure | Not done | Keep #328 open until all P2 items below are completed. |

## Current high-level plan

The remaining work should be completed as a sequence of small PRs. Each PR should
solve one coherent problem, add regression tests, update docs where needed and
pass `task ci` before merge.

Recommended order:

1. PR-328-1 — Define execution policy for non-export/non-erase DSR request types.
2. PR-328-2 — Accept requester details on DSR submissions.
3. PR-328-3 — Separate export download URL issuance from delivery evidence.
4. PR-328-4 — Add real invite delivery provider and prevent NoOp delivery in protected environments.
5. PR-328-5 — Add first-class ops integration for privacy export retention runner.
6. PR-328-6 — Harden production runtime and remaining secret configuration fields.
7. PR-328-7 — Add PostgreSQL export-provider integration coverage.
8. PR-328-8 — Add streaming archive generation for large DSR exports.
9. PR-328-9 — Add authorised representative workflow for DSR requests.
10. PR-328-10 — Final #328 closure reconciliation.

## PR-328-1 — Define execution policy for non-export/non-erase DSR request types

Priority: P2
Type: `feat(privacy)` or `fix(privacy)` depending on chosen contract
Status: Not started

### Problem

The DSR model accepts these request types:

- `access`
- `export`
- `erase`
- `rectify`
- `restrict`
- `object`
- `portability`

The fulfilment pipeline currently supports only:

- `export`
- `erase`

This means non-export/non-erase requests can enter the lifecycle but cannot be
fulfilled through a concrete execution policy.

### Recommended solution

For this backend template, choose the safest contract first:

- keep `export` and `erase` as executable request types;
- make unsupported types explicit `manual_review_only` or reject public
  submission until concrete policy exists;
- prevent an ambiguous approved-but-unfulfillable state;
- document the exact contract in API docs and privacy docs.

Preferred implementation path:

1. Add a central DSR request-type capability map.
2. Mark `export` and `erase` as `executable`.
3. Mark `access`, `rectify`, `restrict`, `object`, `portability` as either:
   - `manual_review_only`, or
   - `not_publicly_submittable`.
4. Update submission/service validation to enforce the selected policy.
5. Add tests for every request type.
6. Update docs and OpenAPI contract expectations.

### Failure cases to cover

- Unsupported request type cannot be approved into an unfulfillable state.
- Unsupported request type cannot be fulfilled accidentally.
- Existing `export` flow still works.
- Existing `erase` flow still works.
- Idempotency behaviour is stable for rejected/unsupported submissions.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_data_subject_request_service.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_platform_erasure_execution_api.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/contracts/test_privacy_docs_contract.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
✨ feat(privacy): define execution policy for non-export DSR request types
```

### Suggested commit message

```text
✨ feat(privacy): define DSR request type execution policy

- declare executable and manual-review-only DSR request types
- prevent unsupported DSR types from reaching ambiguous fulfilment states
- add service and contract coverage for each request type
```

## PR-328-2 — Accept requester details on DSR submissions

Priority: P2
Type: `feat(privacy)`
Status: Not started

### Problem

`CreateDataSubjectRequest` currently accepts only `request_type`. The service can
store `requester_note`, but the self-service API does not expose it.

This is weak for `rectify`, `restrict`, `object`, `access` and `portability`,
because the requester cannot explain what they are asking for.

### Recommended solution

1. Add `requester_note: str | None = None` to `CreateDataSubjectRequest`.
2. Keep `extra="forbid"`.
3. Reuse the service length validation.
4. Pass the note from the API route into `DataSubjectRequestService.submit_request`.
5. Add API tests and service tests.
6. Ensure audit metadata does not store full note contents.

### Failure cases to cover

- Note over max length is rejected.
- Empty/whitespace note is normalised or handled consistently.
- Idempotency fingerprint includes the note.
- Audit event remains minimal and does not leak the full requester note.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_data_subject_request_service.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_data_subject_requests_api.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
✨ feat(privacy): accept requester details on DSR submissions
```

### Suggested commit message

```text
✨ feat(privacy): accept requester notes on DSR submissions

- expose requester_note in self-service DSR creation
- preserve existing length and idempotency validation
- add API and service coverage for requester notes
```

## PR-328-3 — Separate export download URL issuance from delivery evidence

Priority: P2
Type: `feat(privacy)`
Status: Not started

### Problem

Download URL generation currently increments download metadata and marks the DSR
execution state as delivered. For S3-compatible presigned URLs, the app only
knows that a URL was issued, not that the user actually downloaded the archive.

### Recommended solution

1. Rename current semantics to URL issuance where appropriate.
2. Track URL issuance separately from confirmed delivery.
3. Add explicit delivery evidence workflow:
   - manual platform confirmation, or
   - storage webhook/event integration, or
   - explicit user acknowledgement endpoint.
4. Do not mark DSR execution as `DELIVERED` unless the chosen delivery evidence
   condition is met.
5. Add audit events for URL issued and delivery confirmed.

### Failure cases to cover

- URL issued but not downloaded.
- URL expired before confirmed delivery.
- Multiple URLs issued for the same artifact.
- Platform/manual confirmation cannot be performed on expired/missing artifact.
- Existing download URL rate limit still applies.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_export_artifact_service.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_export_artifacts_api.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
✨ feat(privacy): separate export URL issuance from delivery evidence
```

### Suggested commit message

```text
✨ feat(privacy): separate export URL issuance from delivery evidence

- track download URL issuance separately from confirmed delivery
- avoid marking DSR exports delivered from presigned URL creation alone
- add audit and regression coverage for export delivery states
```

## PR-328-4 — Add real invite delivery provider and prevent NoOp delivery in protected environments

Priority: P2
Type: `feat(invites)` / `security(invites)`
Status: Not started

### Problem

`NoOpInviteTokenSink.deliver()` returns successfully without sending anything.
The outbox worker marks invite events as processed after the sink returns.
Therefore staging/prod can silently process invite events without delivering
invite tokens unless a real sink is injected by deployment code.

### Recommended solution

1. Add an explicit invite delivery provider setting.
2. Keep NoOp only for local/test.
3. Reject `dev`, `staging`, `prod` startup when invite delivery is enabled and
   provider is NoOp.
4. Add at least one real provider abstraction or a clear SMTP/provider interface.
5. Ensure delivery failures keep retry/failure semantics.
6. Ensure raw invite tokens are never logged.

### Failure cases to cover

- Protected environment + enabled invite delivery + NoOp provider fails startup.
- Delivery success marks outbox event processed.
- Delivery failure marks failed attempt and remains observable/retryable.
- Malformed payload still follows existing failure path.
- Raw invite token does not appear in logs.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/invites tests/outbox
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/core/config
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
✨ feat(invites): require real invite delivery outside local tests
```

### Suggested commit message

```text
✨ feat(invites): require real invite delivery in protected environments

- add explicit invite delivery provider selection
- keep NoOp invite delivery limited to local and test environments
- preserve retry semantics when delivery providers fail
```

## PR-328-5 — Add first-class ops integration for privacy export retention runner

Priority: P2
Type: `chore(privacy)`
Status: Not started

### Problem

The retention helper and CLI exist, including dry-run and batch-size handling.
However, `Taskfile.yml` exposes first-class export worker commands but not
first-class retention runner commands.

### Recommended solution

1. Add Taskfile commands:
   - `privacy:retention:once`
   - `privacy:retention:dry-run`
2. Document production scheduling patterns:
   - systemd timer;
   - Kubernetes CronJob;
   - external scheduler;
   - one-shot manual run.
3. Add CLI parser/import smoke tests if not already covered.
4. Keep runtime behaviour unchanged.

### Failure cases to cover

- Dry-run does not mutate database or storage.
- Invalid batch size fails clearly.
- Command path works from repository root through Taskfile.
- Docs do not suggest backend-relative paths incorrectly.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_export_artifact_service.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_privacy_retention_cli.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template> task privacy:retention:dry-run
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template> task ci
```

### Suggested issue title

```text
🧹 chore(privacy): add retention runner ops commands
```

### Suggested commit message

```text
🧹 chore(privacy): add export retention runner ops commands

- expose privacy export retention one-shot and dry-run Taskfile tasks
- document production scheduling patterns for retention cleanup
- add smoke coverage for retention CLI usage
```

## PR-328-6 — Harden production runtime and remaining secret configuration fields

Priority: P2
Type: `security(core)`
Status: Not started

### Problem

Some secret-like settings are still plain strings. The backend Docker image is
minimal and currently does not define a non-root runtime user, healthcheck, or
explicit writable-path/read-only guidance.

Relevant plain-string secret candidates:

- `security.outbox_token_encryption_key`
- `security.keycloak_client_secret`
- `vault.token`
- `vault.role_id`
- `vault.secret_id`
- `privacy_exports.local_signing_secret`

### Recommended solution

1. Convert remaining secret-like settings to `SecretStr`.
2. Add validators that preserve current behaviour while masking values by
   default.
3. Add tests for `repr`, `model_dump`, and validation paths.
4. Add protected-environment default/placeholder guardrails where appropriate.
5. Harden Docker runtime:
   - non-root user;
   - controlled writable directories;
   - healthcheck or documented probe;
   - read-only filesystem guidance.
6. Update docs and `.env.example` placeholders.

### Failure cases to cover

- Placeholder/default secrets rejected in protected environments.
- Secret values are masked in model dumps/repr/log-safe paths.
- Runtime still reads secrets where `.get_secret_value()` is needed.
- Docker image can still start after switching to non-root user.
- Local dev remains usable.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/core/config
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/security
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template> docker build -f docker/backend/Dockerfile backend
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template> task ci
```

### Suggested issue title

```text
🛡️ security(core): harden runtime secrets and backend container
```

### Suggested commit message

```text
🛡️ security(core): harden runtime secrets and backend container

- mask remaining secret-like configuration fields with SecretStr
- reject unsafe placeholder secrets in protected environments
- run the backend container as a non-root user with documented writable paths
```

## PR-328-7 — Add PostgreSQL export-provider integration coverage

Priority: P2
Type: `test(privacy)`
Status: Not started

### Problem

Privacy export and erasure preview code uses JSON predicates and cross-table
selectors. SQLite-backed tests do not fully prove PostgreSQL semantics for JSON
expressions, UUID comparisons, ordering, and joins.

### Recommended solution

1. Add opt-in external DB tests marked `external_db`.
2. Cover outbox JSON email matching.
3. Cover audit/DSR/export-artifact/provider joins.
4. Keep default CI fast by not running external DB tests unless explicitly
   requested.
5. Document how to run the suite locally.

### Failure cases to cover

- JSON email predicate matches expected PostgreSQL rows.
- Case-insensitive subject matching works as intended.
- UUID comparisons and ordering are stable.
- External DB tests are skipped unless `--run-external-db` is provided.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q -m external_db --run-external-db -rs
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task test:external-db
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
🧪 test(privacy): add PostgreSQL export-provider integration coverage
```

### Suggested commit message

```text
🧪 test(privacy): add PostgreSQL coverage for DSR providers

- cover privacy export provider JSON predicates against PostgreSQL
- verify UUID joins and ordering for DSR provider queries
- keep external DB coverage opt-in through existing markers
```

## PR-328-8 — Add streaming archive generation for large DSR exports

Priority: P2
Type: `perf(privacy)`
Status: Not started

### Problem

Export artifact generation currently builds the full export payload and ZIP
archive in memory before writing to storage and checking final size.

### Recommended solution

1. Stream provider records into archive generation where possible.
2. Avoid holding the full archive in memory.
3. Enforce max artifact size during generation.
4. Preserve current JSON ZIP schema compatibility.
5. Ensure failed/oversized exports clean up partial storage writes.
6. Keep existing small export tests passing.

### Failure cases to cover

- Oversized export fails with controlled failure reason.
- Partial storage object is removed or never committed as ready.
- Worker retry semantics remain stable.
- Subjectless/minimised DSR protections still apply.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_export_artifact_service.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_privacy_export_worker_ops.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
⚡️ perf(privacy): stream DSR export archive generation
```

### Suggested commit message

```text
⚡️ perf(privacy): stream DSR export archive generation

- avoid materialising full export archives in memory
- enforce artifact size limits during archive generation
- clean up partial writes when large exports fail
```

## PR-328-9 — Add authorised representative workflow for DSR requests

Priority: P2
Type: `feat(privacy)`
Status: Not started

### Problem

Current DSR submission is self-service only. The requester and subject are always
the same local user. There is no separate flow for authorised representatives.

### Recommended solution

1. Add a separate representative submission schema and service flow.
2. Store authority evidence metadata or evidence references.
3. Require platform review/verification before execution.
4. Preserve requester identity, subject identity, verifier identity and audit
   records separately.
5. Prevent representative requests from bypassing subject identity checks.

### Failure cases to cover

- Representative request cannot execute before verification.
- Requester cannot impersonate another subject without evidence.
- Audit records show requester, subject and verifier.
- Self-service requests keep current simple path.

### Suggested tests

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_data_subject_request_service.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> uv run --locked pytest -q tests/privacy/test_data_subject_requests_api.py
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
```

### Suggested issue title

```text
✨ feat(privacy): support authorised representative DSR workflows
```

### Suggested commit message

```text
✨ feat(privacy): support authorised representative DSR workflows

- separate requester and subject identity for representative requests
- require authority evidence review before execution
- add audit coverage for representative verification
```

## PR-328-10 — Final #328 closure reconciliation

Priority: P1
Type: `docs(privacy)`
Status: Not started

### Goal

Close #328 only after PR-328-1 through PR-328-9 are merged and verified.

### Scope

1. Re-run a final repository review against `main`.
2. Update `SESSION_NOTES.md` and privacy docs if needed.
3. Ensure all P2 items above are either done or intentionally moved out of #328
   by explicit decision.
4. Run final checks.
5. Close #328 with a clear summary.

### Final verification commands

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task ci
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task test:privacy
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task test:contracts
```

Optional external DB check:

```powershell
PS C:\Users\61706\Documents\_FastAPI_Template\fastapi-saas-template\backend> task test:external-db
```

### Suggested closing comment for #328

```text
Closing after completing the full #328 privacy/DSR closure plan.

Completed scope:
- backend DSR foundation and lifecycle;
- self-service and platform DSR APIs;
- export artifact workflow and delivery semantics;
- platform erasure execution;
- inventory-aligned erasure coverage;
- explicit request-type execution policy;
- requester details support;
- invite delivery operational guardrails;
- retention runner ops integration;
- production/runtime secret hardening;
- PostgreSQL provider integration coverage;
- large export generation hardening;
- authorised representative workflow;
- final documentation and contract reconciliation.

Final verification passed with task ci.
```

### Suggested commit message

```text
📝 docs(privacy): complete full DSR closure plan for issue 328

- reconcile completed privacy and DSR follow-up work
- document final verification for issue 328 closure
- preserve remaining out-of-scope product roadmap separately
```

## Short PR roadmap table

| Order | PR | Priority | Type | Blocks #328 closure under current decision | Status |
|---:|---|---:|---|---:|---|
| 1 | Define execution policy for non-export DSR types | P2 | feat/fix | Yes | Not started |
| 2 | Accept requester details on DSR submissions | P2 | feat | Yes | Not started |
| 3 | Separate URL issuance from delivery evidence | P2 | feat | Yes | Not started |
| 4 | Real invite delivery provider / NoOp guard | P2 | feat/security | Yes | Not started |
| 5 | Retention runner Taskfile and ops docs | P2 | chore | Yes | Not started |
| 6 | Runtime secrets and Docker hardening | P2 | security | Yes | Not started |
| 7 | PostgreSQL DSR provider integration tests | P2 | test | Yes | Not started |
| 8 | Streaming DSR export archive generation | P2 | perf | Yes | Not started |
| 9 | Authorised representative DSR workflow | P2 | feat | Yes | Not started |
| 10 | Final #328 closure reconciliation | P1 | docs | Yes | Not started |

## Notes for future work

- Keep PRs small. Do not combine unrelated security, ops and product-policy work.
- Every PR should include tests for failure cases.
- Every PR should keep code line length within 88 characters.
- Use backend-relative test paths when running pytest from the backend directory.
- Do not claim #328 closure until all rows in the roadmap table are done or
  explicitly removed from #328 scope by a documented decision.
