# End-to-end and integration test conventions

## 1. Scope

- End-to-end and integration tests may start real ephemeral infrastructure via Testcontainers.
- Tests must never connect to production resources.
- Tests must not depend on manually started local services unless that mode is explicitly documented as opt-in.

## 2. Markers

- Use `@pytest.mark.integration` for tests that depend on Docker or external services.
- Use `@pytest.mark.anyio` for async integration tests where needed.

Run examples:

```bash
pytest -q
pytest -q -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m integration
```

## 3. Testcontainers

- Prefer ephemeral Docker containers started by each test/fixture.
- Pin image tags for reproducibility.
- Expose only required ports.
- Wait for readiness before exercising the app.
- Use bounded timeouts for every wait/polling loop.
- Clean up container-backed clients and resources.

## 4. Environment isolation

- Set environment variables via `monkeypatch` before `create_app()`.
- Call `reset_settings_cache()` after environment changes.
- Create the app only after environment is fully configured.
- Explicitly close/cleanup runtime clients when tests allocate them.

## 5. Safety rules

- Never use real production DB/Redis/Collector endpoints.
- Use random prefixes/suffixes for tests that can share stateful stores.
- For DB tests, use migrated test DBs or ephemeral Postgres.
- For Redis and rate-limit tests, use isolated prefixes.
- For OpenTelemetry tests, use an ephemeral Collector endpoint.

## 6. Assertions

- Assert externally visible behavior first (HTTP status, response contracts, effects).
- Avoid brittle full log snapshot assertions.
- Use eventual polling for asynchronous exports.
- Include last available logs/output in timeout failure messages.

## 7. When to ask the user

Ask before implementation when a test requires:

- choosing subprocess isolation vs in-process speed;
- adding dependencies;
- introducing new Docker services;
- changing production code to make tests possible.
