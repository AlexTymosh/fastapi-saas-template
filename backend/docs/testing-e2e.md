# End-to-end and integration test conventions

## Test selection policy

The backend test suite uses a domain-first layout and a small marker set.

Main rule:

- folders describe the domain or subsystem;
- file names describe the test type for humans;
- markers are used only for execution cost or cross-cutting risk selection.

The main GitHub backend quality gate runs all non-external-db backend tests exactly once:

```bash
cd backend
uv run --frozen pytest -q -m "not external_db"
```

Focused runs such as security-only, authz-only, privacy-only, contract-only, container-only, or domain-folder-only commands are local/manual diagnostics. They must not be added as mandatory duplicate CI gates when already covered by the broad non-external-db run.

## Test levels

### Default lightweight tests

- Fast tests.
- No Docker.
- No external services.
- No network.
- No execution marker is required.
- A normal unmarked test is treated as lightweight/default.

### Integration

- Tests combining multiple components.
- May use ephemeral infrastructure.
- Use `@pytest.mark.integration`.

### E2E

- Full API flow tests through an HTTP client.
- Should exercise realistic application behaviour.
- Use `@pytest.mark.e2e`.

### Container

- Tests requiring Docker/Testcontainers or similar containerised ephemeral infrastructure.
- Use `@pytest.mark.container`.
- Container tests may also be `integration` or `e2e`.

### Slow

- Tests intentionally slower than the default suite.
- Use `@pytest.mark.slow`.
- Slow tests still run in the main safe CI suite unless they are also `external_db`.

### Contract

- API/schema/client compatibility tests.
- Use `@pytest.mark.contract`.
- Contract tests usually live under `tests/contracts` or in explicit OpenAPI contract files.

### External DB

- Opt-in only.
- Uses `TEST_DATABASE_URL`.
- Must never run by default.
- Requires both `--run-external-db` and `ENABLE_EXTERNAL_MIGRATION_DB_TEST=1`.
- Use `@pytest.mark.external_db`.

### External Redis Cluster smoke tests

- Opt-in only.
- Uses `TEST_REDIS_CLUSTER_URL`.
- Intended for Redis Cluster topology validation that cannot be proven with the single-node Testcontainers Redis fixture.
- Should be marked `integration`; do not mark it `external_db` because it does not use `TEST_DATABASE_URL` or database migrations.
- The smoke test does not start a Redis Cluster automatically. Provide a URL
  pointing to a real Redis Cluster started manually, via Docker, or through a
  dedicated local Compose/Testcontainers setup outside the default safe suite.
- The test should skip when `TEST_REDIS_CLUSTER_URL` is not provided so the regular safe CI suite remains self-contained.
- If `TEST_REDIS_CLUSTER_URL` is provided with a non-cluster scheme such as `redis://`, the test should fail fast to avoid false-positive single-node coverage.
- Cluster URLs should use the `limits` storage scheme, for example `redis+cluster://localhost:7000,localhost:7001/0`; Redis Cluster supports database `0` only.
- Do not rely on the default local Compose stack for Redis Cluster smoke tests.

## Marker policy

### Execution markers

Keep:

- `@pytest.mark.integration`
- `@pytest.mark.e2e`
- `@pytest.mark.external_db`
- `@pytest.mark.container`
- `@pytest.mark.slow`
- `@pytest.mark.contract`

### Cross-cutting risk markers

Keep:

- `@pytest.mark.security`
- `@pytest.mark.auth`
- `@pytest.mark.authz`
- `@pytest.mark.privacy`

### Retired legacy markers

Do not use:

- `@pytest.mark.unit`
- `@pytest.mark.rate_limit`
- `@pytest.mark.audit`
- `@pytest.mark.cors`
- `@pytest.mark.bola`
- `@pytest.mark.logging_security`
- `@pytest.mark.secrets`

Use folders for domain/subsystem selection instead:

```bash
cd backend
uv run pytest -q tests/rate_limit
uv run pytest -q tests/audit
uv run pytest -q tests/secrets
uv run pytest -q tests/logging
```

Use cross-cutting markers only when selection cannot be represented by one folder:

```bash
cd backend
uv run pytest -q -m "security and not external_db"
uv run pytest -q -m "authz and not external_db"
uv run pytest -q -m "privacy and not external_db"
```

## Dependency setup

Backend dependency management uses `uv`.

Install development dependencies from the lockfile:

```bash
cd backend
uv sync --group dev
```

Do not use `pip install -e ".[dev]"`, `requirements-dev.txt`, or `pip-tools`.
`backend/uv.lock` is the only dependency lock source.

## CI behaviour

Docs-only pull requests still start the CI workflow, but path filtering skips the expensive backend quality gate. The aggregate `CI status` job is the branch-protection-safe required check and passes when the backend gate is skipped because no backend/tooling/CI-relevant paths changed.

The mandatory backend quality gate is:

```bash
uv lock --check
uv sync --frozen --group dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pytest -q -m "not external_db"
```

Do not add overlapping mandatory pytest commands to the main CI workflow. In one CI workflow, a second pytest command must not select a subset that is already covered by the broad non-external-db run.

## Taskfile commands

Preferred commands from the repository root:

```bash
task test:lightweight
task test:safe
task test:security
task test:auth
task test:authz
task test:privacy
task test:contracts
task test:integration
task test:e2e
task test:container
task test:slow
task ci
```

The old unit-test task name is intentionally not provided as a compatibility alias; lightweight/default tests are selected with `task test:lightweight`.

`task pre-push` and `task ci` intentionally run only:

1. `task deps:check`
2. `task lint`
3. `task test:safe`

Focused test tasks remain available for manual diagnosis, but they are not part of the mandatory aggregate quality gate.

## Useful collection checks

```bash
cd backend
uv run --frozen pytest --collect-only -q
uv run --frozen pytest --collect-only -q -m "not external_db"
uv run --frozen pytest --collect-only -q -m "external_db"
uv run --frozen pytest --collect-only -q -m "integration"
uv run --frozen pytest --collect-only -q -m "container"
uv run --frozen pytest --collect-only -q -m "contract"
uv run --frozen pytest --collect-only -q -m "security"
```

Expected relationship:

- plain collection = all tests;
- `not external_db` = all default CI-safe tests;
- `external_db` = opt-in external DB tests only.

## Fixture scoping guidance

Do not use `pytest_plugins` in non-root `conftest.py` files. Pytest deprecates this pattern because loaded plugins affect the whole test tree even when the declaration is inside a nested `conftest.py`.

Fixture implementation should live in `tests/fixtures/`. Domain-local `conftest.py` files should explicitly re-export only the heavier fixtures they need, for example:

```python
from tests.fixtures.redis import redis_integration_url as redis_integration_url

__all__ = ["redis_integration_url"]
```

The root `tests/conftest.py` may re-export lightweight shared fixtures that are broadly used across many folders, but it should not contain fixture implementation details or container startup code.

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

For OTLP integration/e2e verification run:

```bash
cd backend
uv run pytest tests/observability/test_otlp_export_integration.py -q -m "integration and e2e and container" -rs
```

## When to ask the user

Codex/AI agents must ask before:

- adding new dependencies;
- introducing new Docker services;
- choosing subprocess isolation vs in-process tests;
- changing production code to make tests possible;
- changing authentication strategy for E2E tests.
