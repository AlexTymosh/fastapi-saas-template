# End-to-end and integration test conventions

## 1. Scope

- End-to-end/integration tests may start real **ephemeral** infrastructure through Testcontainers.
- Tests must never use production resources.
- Tests must not depend on manually started local services unless this is explicitly documented as an opt-in workflow.

## 2. Markers

- Use `@pytest.mark.integration` for tests that need Docker or other external services.
- Use `@pytest.mark.anyio` for async tests when needed.

Examples:

```bash
pytest -q
pytest -q -m integration -rs
pytest tests/observability/test_otlp_export_integration.py -q -m integration
```

## 3. Testcontainers

- Prefer ephemeral Docker containers over shared local services.
- Pin image tags.
- Expose only required ports.
- Wait for readiness before running assertions.
- Use bounded timeouts and actionable failure messages.
- Clean up clients/resources after tests.

## 4. Environment isolation

- Configure env vars via `monkeypatch` before `create_app()`.
- Call `reset_settings_cache()` after env changes.
- Create app instances only after env setup is complete.
- Close runtime clients/resources at test teardown if needed.

## 5. Safety rules

- Never use real production DB/Redis/Collector in tests.
- Use random prefixes/suffixes for shared stores to avoid collisions.
- For DB tests, use migrated test DB or ephemeral Postgres.
- For Redis/rate-limit tests, use isolated prefixes.
- For OTel tests, use an ephemeral Collector endpoint.

## 6. Assertions

- Assert externally visible behavior first (status codes, payload contracts).
- Avoid brittle full log snapshot assertions.
- Use eventual polling for async/exporter behavior.
- Include last logs/output in failure messages for diagnostics.

## 7. When to ask the user

Ask before implementation if a test requires:

- choosing subprocess isolation vs in-process speed trade-off;
- adding new dependencies;
- introducing new Docker services;
- changing production code to make testing possible.
