# End-to-end and integration test conventions

## Test levels

### Default lightweight tests

- Fast tests.
- No Docker.
- No external services.
- No network.
- No marker is required for normal lightweight/default tests.

### Integration

- Tests combining 2-3 components.
- May use Testcontainers.
- Examples: repository + PostgreSQL, Redis client, rate limiter + Redis.

### E2E

- Full API flow tests through an HTTP client.
- Should exercise realistic application behaviour.
- Should use ephemeral infrastructure via Testcontainers.
- Should avoid production resources.

### External DB

- Opt-in only.
- Uses `TEST_DATABASE_URL`.
- Must never run by default.
- Requires both `--run-external-db` and `ENABLE_EXTERNAL_MIGRATION_DB_TEST=1`.
- Intended only for debugging persistent local test DBs.

## Dependency setup

Backend dependency management uses `uv`.

Install development dependencies from the lockfile:

```bash
cd backend
uv sync --group dev
```

Do not use `pip install -e ".[dev]"`, `requirements-dev.txt`, or `pip-tools`.
`backend/uv.lock` is the only dependency lock source.

## CI test-selection policy

The main GitHub backend quality gate runs all non-external-db backend tests exactly once:

```bash
cd backend
uv run --frozen pytest -q -m "not external_db"
```

Security-only, authz-only, contract-only, or domain-folder-only commands are focused local/manual diagnostics. They must not be added as mandatory duplicate CI gates when they are already covered by the broad non-external-db run.

Docs-only pull requests still start the CI workflow, but path filtering skips the expensive backend quality gate. The aggregate `CI status` job is the branch-protection-safe required check and passes when the backend gate is skipped because no backend/tooling/CI-relevant paths changed.

## Taskfile commands

Preferred commands from the repository root:

```bash
task test:unit
task test:safe
task test:security
task test:contracts
task test:integration
task test:e2e
task ci
```

The Taskfile wraps `uv run` so developers and agents do not need to type it manually for common checks.

`task pre-push` and `task ci` intentionally run only:

1. `task deps:check`
2. `task lint`
3. `task test:safe`

Focused test tasks remain available for manual diagnosis, but they are not part of the mandatory aggregate quality gate.

## Marker policy

Domain folders are preferred for domain/subsystem selection. For example, prefer paths such as `tests/rate_limit`, `tests/audit`, `tests/api`, or `tests/contracts` for focused domain runs instead of adding new micro-markers.

Markers are for execution cost and cross-cutting risk classification:

- no marker: normal lightweight/default test;
- execution markers: cost, infrastructure, or opt-in execution semantics;
- cross-cutting markers: security/privacy/authentication/authorization risk classification.

### Keep cross-cutting markers

- `@pytest.mark.security`
- `@pytest.mark.auth`
- `@pytest.mark.authz`
- `@pytest.mark.privacy`

### Keep execution markers

- `@pytest.mark.integration`
- `@pytest.mark.e2e`
- `@pytest.mark.external_db`
- `@pytest.mark.container`
- `@pytest.mark.slow`
- `@pytest.mark.contract`

### Deprecated marker direction

- `@pytest.mark.unit` is deprecated; lightweight tests should normally be unmarked.
- `@pytest.mark.rate_limit`, `@pytest.mark.audit`, `@pytest.mark.cors`, `@pytest.mark.bola`, `@pytest.mark.logging_security`, and `@pytest.mark.secrets` are legacy/micro-markers and should not be added to new tests.
- Prefer folders such as `tests/rate_limit` or `tests/audit` for domain-specific runs.

Do not remove old marker definitions or old marker usages until a complete cleanup proves that the usages are gone and the test suite still passes.

## Safe and focused commands

Fast unit-style suite for legacy marker-based local selection:

```bash
cd backend
uv run pytest -q -m "not integration and not e2e and not external_db"
```

Broad safe suite used by CI:

```bash
cd backend
uv run pytest -q -m "not external_db"
```

Security marker collection sanity check:

```bash
cd backend
uv run pytest -q -m "security and not external_db" --collect-only
```

Security regressions only:

```bash
cd backend
uv run pytest -q -m "security and not external_db"
```

Focused cross-cutting or legacy slices:

```bash
cd backend
uv run pytest -q -m auth
uv run pytest -q -m authz
uv run pytest -q -m bola
uv run pytest -q -m rate_limit
uv run pytest -q -m audit
uv run pytest -q -m cors
uv run pytest -q -m logging_security
```

Contract tests:

```bash
cd backend
uv run pytest -q tests/contracts
```

Integration + E2E only:

```bash
cd backend
uv run pytest -q -m "integration or e2e" -rs
```

External DB only:

```bash
cd backend
uv run pytest -q -m external_db --run-external-db -rs
```

Important safety notes:

- `external_db` tests require explicit `--run-external-db`.
- `external_db` tests also require `ENABLE_EXTERNAL_MIGRATION_DB_TEST=1`.
- Do not set `ENABLE_EXTERNAL_MIGRATION_DB_TEST` globally in your shell profile.

## Quality gate

Local equivalent of the mandatory GitHub backend quality gate:

```bash
task ci
```

Direct equivalent from `backend/`:

```bash
uv lock --check
uv sync --frozen --group dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pytest -q -m "not external_db"
```

Use `--frozen` in CI and other strict environments so dependency resolution cannot silently update the lockfile.

## Fixture scoping guidance

Do not use `pytest_plugins` in non-root `conftest.py` files. Pytest documentation deprecates `pytest_plugins` in non-root `conftest.py` files because loaded plugins affect the whole test tree.

Future fixture scoping should prefer explicit fixture re-exports from domain-local `conftest.py` files, for example:

```python
from tests.fixtures.redis import redis_client as redis_client

__all__ = ["redis_client"]
```

## Testcontainers rules

- Prefer ephemeral Docker containers.
- Pin image tags.
- Expose only required ports.
- Wait for readiness with bounded timeouts.
- TCP readiness is not always enough for containerised services.
- Prefer application-level readiness signals such as health endpoints or stable startup logs when available.
- Use random prefixes/suffixes for shared stores.
- Do not rely on docker compose state.
- `docker compose down -v` must not break pre-push tests.

## E2E authoring rules

- E2E tests should validate user journeys, not a single function.
- Prefer `AsyncClient` or `TestClient` through the real FastAPI app.
- Use app lifespan.
- Avoid mocks in E2E, except controlled external side-effect boundaries such as email delivery.
- For auth-heavy flows, use a documented test auth strategy or a test Keycloak realm; do not silently bypass security without documenting why.
- Use factories/builders for test data when domain model grows.
- Avoid brittle timing assertions.
- Use eventual polling for async exports.
- Include last logs/output in timeout failures.
- OTLP Collector export tests should use an ephemeral OpenTelemetry Collector via Testcontainers.
- For OTLP integration/e2e verification run:

```bash
cd backend
uv run pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e" -rs
```

## When to ask the user

Codex/AI agents must ask before:

- adding new dependencies;
- introducing new Docker services;
- choosing subprocess isolation vs in-process tests;
- changing production code to make tests possible;
- changing authentication strategy for E2E tests.
