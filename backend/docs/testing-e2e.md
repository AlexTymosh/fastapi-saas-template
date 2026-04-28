# End-to-end and integration test conventions

## Test levels

### Unit

- Fast tests.
- No Docker.
- No external services.
- No network.

### Integration

- Tests combining 2–3 components.
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

## Markers

Use explicit markers for all tests:

- `@pytest.mark.unit`
- `@pytest.mark.integration`
- `@pytest.mark.e2e`
- `@pytest.mark.external_db`

## Safe commands

Fast safe suite:

```bash
pytest -q -m "not integration and not e2e and not external_db"
```

Pre-push safe suite:

```bash
pytest -q -m "not external_db"
```

Integration + E2E only:

```bash
pytest -q -m "integration or e2e" -rs
```

External DB only:

```bash
pytest -q -m external_db --run-external-db -rs
```

Important safety notes:

- `external_db` tests require explicit `--run-external-db`.
- `external_db` tests also require `ENABLE_EXTERNAL_MIGRATION_DB_TEST=1`.
- Do not set `ENABLE_EXTERNAL_MIGRATION_DB_TEST` globally in your shell profile.

## Testcontainers rules

- Prefer ephemeral Docker containers.
- Pin image tags.
- Expose only required ports.
- Wait for readiness with bounded timeouts.
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

## When to ask the user

Codex/AI agents must ask before:

- adding new dependencies;
- introducing new Docker services;
- choosing subprocess isolation vs in-process tests;
- changing production code to make tests possible;
- changing authentication strategy for E2E tests.
