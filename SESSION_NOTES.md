# SESSION_NOTES

## Current Focus

Final documentation reconciliation after the #328 DSR/privacy backend
implementation.

## Current Project State

The backend DSR/privacy scope is implemented for the current SaaS template
inventory.

Implemented areas:

- DSR persistence, repository, service lifecycle, user API, and platform API;
- cross-table subject export providers;
- export artifact service, worker command, local development storage,
  S3-compatible storage, download URL generation, and retention runner;
- platform erasure execution API;
- inventory-aligned erasure orchestration with executable, retained-by-policy,
  and manual-review provider decisions;
- automatic fulfilment after successful approved erasure execution;
- contract tests for privacy docs, inventory, export providers, erasure
  coverage, provider decisions, platform permissions, and rate-limit policy
  coverage.

## Current #328 Status

Issue #328 is ready to close after broad CI is confirmed green.

Remaining work should be tracked as separate follow-up issues and must not be
treated as #328 blockers.

Non-blocking follow-up categories:

- streaming archive generation for very large exports;
- PostgreSQL-specific export-provider integration coverage;
- explicit export delivery evidence semantics;
- authorised representative workflows;
- frontend/UI;
- execution pipelines for rectify/restrict/object/access/portability request
  types;
- production hardening work that is not part of the current #328 backend scope.

## Preferred Local Commands

Install development dependencies from `backend/`:

```bash
uv sync --group dev
```

Run common checks from the repository root:

```bash
task lint
task test:safe
task test:security
task test:contracts
task ci
```

Direct backend equivalents from `backend/`:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not external_db"
```

Focused privacy/docs checks from `backend/`:

```bash
uv run pytest -q tests/contracts/test_privacy_docs_contract.py
uv run pytest -q -m "privacy and not external_db"
uv run pytest -q -m contract
```

## Dependency and Tooling Sources of Truth

- `.python-version` pins Python 3.12.
- `backend/pyproject.toml` contains runtime dependencies and
  `[dependency-groups].dev`.
- `backend/uv.lock` is the only dependency lock source.
- `Taskfile.yml` provides the stable developer/agent command interface.
- `.pre-commit-config.yaml` runs local hooks through `uv`.
- `.github/workflows/ci.yml` runs the backend quality gate through `uv`.
- `docker/backend/Dockerfile` installs runtime dependencies through
  `uv sync --frozen --no-dev --no-editable`.

Legacy dependency workflow is removed:

- no Poetry;
- no `pip-tools`;
- no `requirements.txt`;
- no `requirements-dev.txt`.

## Files That Must Stay Aligned

- `README.md`
- `AGENTS.md`
- `backend/docs/current-state.md`
- `backend/docs/privacy-dsr.md`
- `backend/docs/privacy-dsr-328-closure-checklist.md`
- `backend/docs/privacy-export-artifacts.md`
- `backend/docs/rate-limiting.md`
- `backend/docs/admin-frontend-client-generation.md`
- `backend/docs/access-control/en/platform-access.en.md`
- `backend/tests/contracts/test_privacy_docs_contract.py`
- `SESSION_NOTES.md`
- `Taskfile.yml`
- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`
- `docker/backend/Dockerfile`

## Known Risks

- Documentation can drift back to old #328 slice notes that describe implemented
  DSR/export/erasure components as pending.
- Historical implementation-slice documents must be clearly marked as historical
  and must not be used as the current closure source of truth.
- If `requirements.txt` or `requirements-dev.txt` reappear, that is likely a
  regression unless explicitly justified.
- If Codex runs raw `pytest`/`ruff` without `uv run` or Taskfile, it may use the
  wrong environment.
- GitHub Actions should be verified as green after each tooling or documentation
  reconciliation change.

## Next Recommended Step

After this documentation reconciliation, close #328 only after confirming:

```bash
task ci
```

and the GitHub Actions backend quality gate are green.

## Historical notes

Earlier session notes mentioned DSR API/export/erasure as follow-up scope. Those
notes are now superseded by the completed #328 backend implementation and are
retained only as historical context.
