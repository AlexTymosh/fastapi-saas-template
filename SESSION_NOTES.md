# SESSION_NOTES

## Current Focus

Align documentation with the completed `uv`, Docker, Taskfile, pre-commit, and GitHub Actions CI migration.

## Current Project State

The backend dependency workflow now uses `uv`.

Current dependency/tooling sources of truth:

- `.python-version` pins Python 3.12.
- `backend/pyproject.toml` contains runtime dependencies and `[dependency-groups].dev`.
- `backend/uv.lock` is the only dependency lock source.
- `Taskfile.yml` provides the stable developer/agent command interface.
- `.pre-commit-config.yaml` runs local hooks through `uv`.
- `.github/workflows/ci.yml` runs a path-filtered backend quality gate through `uv` and exposes an aggregate `CI status` job.
- `docker/backend/Dockerfile` installs runtime dependencies through `uv sync --frozen --no-dev --no-editable`.

Legacy dependency workflow is removed:

- no Poetry;
- no `pip-tools`;
- no `requirements.txt`;
- no `requirements-dev.txt`.

## Preferred Local Commands

Install development dependencies:

```bash
cd backend
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

Direct backend equivalents:

```bash
cd backend
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not external_db"
```

Focused security and contract commands remain available for local/manual diagnosis.

## CI Commands

GitHub Actions should run the strict backend quality gate once for backend/tooling/CI-relevant changes:

```bash
cd backend
uv lock --check
uv sync --frozen --group dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pytest -q -m "not external_db"
```

## Recently Completed

- Migrated backend development dependencies from `[project.optional-dependencies].dev` to `[dependency-groups].dev`.
- Added `backend/uv.lock`.
- Removed `pip-tools` from the development workflow.
- Updated `Taskfile.yml` to run lint/tests through `uv`.
- Updated pre-commit hooks to use local `uv` commands.
- Added GitHub Actions backend CI workflow.
- Migrated backend Dockerfile to install runtime dependencies through `uv`.
- Removed legacy `requirements.txt` and `requirements-dev.txt`.

## Files That Must Stay Aligned

- `README.md`
- `AGENTS.md`
- `backend/docs/testing-e2e.md`
- `backend/docs/current-state.md`
- `backend/docs/observability.md`
- `SESSION_NOTES.md`
- `Taskfile.yml`
- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`
- `docker/backend/Dockerfile`

## Known Risks

- Documentation can easily drift back to old `pip install -e ".[dev]"` or `requirements-dev.txt` instructions.
- If `requirements.txt` or `requirements-dev.txt` reappear, that is likely a regression unless explicitly justified.
- If Codex runs raw `pytest`/`ruff` without `uv run` or Taskfile, it may use the wrong environment.
- GitHub Actions should be verified as green after each tooling change.

## Next Recommended Step

After merging documentation alignment, continue with the next backend hardening task only after confirming:

```bash
task ci
```

and the GitHub Actions `Backend quality gate` are green.


## Latest update

- grouped business rate-limit consume path now uses Redis Lua all-or-nothing semantics for Redis-backed execution to close TOCTOU concurrency leaks.
- grouped atomic checks currently target single-node Redis; Redis Cluster needs same-slot hash tags for grouped keys.
