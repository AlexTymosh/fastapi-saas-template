# Test Suite Audit (2026-04-19)

## 1) Tests that are outdated due to project evolution

1. `backend/tests/logging/test_access_log.py`, `test_error_logging_redaction.py`, `test_lifespan_logging.py`, and `backend/tests/app/test_lifespan.py` keep module-level `settings = get_settings()` and then mutate this object with `monkeypatch.setattr(...)`.
   - After the app-factory change that clears settings cache at app construction time, these tests no longer represent runtime behavior reliably, because `create_app()` may read a fresh `Settings` instance.
   - Recommended update: set env vars (`LOGGING__AS_JSON`, `LOGGING__LEVEL`) via `monkeypatch.setenv(...)` and avoid mutating a cached settings object.

2. `backend/tests/api/test_openapi_contract.py` uses aggressive `importlib.reload(...)` for settings/router/main modules.
   - This pattern is now a source of cross-test coupling and stale-reference bugs rather than realistic app usage.
   - Recommended update: prefer factory-based app creation with explicit env setup and cache clear.

## 2) Tests with logic errors

1. Duplicate assertion in `backend/tests/api/test_openapi_contract.py::test_openapi_health_ready_documents_503_problem_response`:
   - `schema_ref` is assigned and asserted twice with identical checks.
   - One duplicate assertion should be removed.

2. In several logging tests, the intended assertion target is config-driven JSON output, but the test setup mutates an in-memory settings object rather than the effective config source. This can produce false positives/negatives depending on cache lifecycle.

## 3) Tests that do not cover logging requirements from `README.draft.md`

The README states a unified structured pipeline with three categories (`application`, `audit`, `security`), common envelope, and sanitization/redaction policy. Current tests are mostly focused on `application` logs and redaction primitives.

Missing coverage:

1. No end-to-end tests proving `audit` and `security` event categories are emitted and preserved in output.
2. No contract-like tests for common envelope fields across categories (e.g., `timestamp`, `level`, `logger`, `service`, `environment`, `version`, `category`, `event`).
3. No tests validating category-specific policy constraints (required fields per category).
4. No tests asserting routing behavior by category (if/when separate sinks are introduced).

## 4) Redundant tests

1. `backend/tests/logging/test_request_id_processor.py::test_add_request_id_from_context` duplicates the same behavior already tested in `backend/tests/logging/test_processors.py::test_add_request_id_from_context`.
2. `backend/tests/logging/test_redaction.py::test_redacts_sensitive_fields` is a strict subset of `backend/tests/logging/test_processors.py::test_redact_sensitive_fields_redacts_flat_fields`.
3. `backend/tests/app/test_lifespan.py::test_lifespan_logs_startup_and_shutdown` and `backend/tests/logging/test_lifespan_logging.py::test_lifespan_logs_startup_and_shutdown` verify near-identical behavior and can be merged.

## 5) Tests to add

1. **Logging category coverage**
   - Add integration tests that emit explicit `category="audit"` and `category="security"` events and validate output envelope fields.

2. **Envelope contract tests**
   - Add parametrized tests ensuring required envelope keys exist for all categories.

3. **Config-driven logging tests**
   - Replace settings-object monkeypatching with env-based setup; add tests that prove `LOGGING__AS_JSON` and `LOGGING__LEVEL` are honored by `create_app()`.

4. **Request-id header configurability**
   - Add integration tests where `REQUEST_CONTEXT__HEADER_NAME` is changed (e.g., `X-Correlation-ID`) and both middleware + error handlers return that header consistently.

5. **Cross-test isolation**
   - Add utility fixture that centralizes env setup + `get_settings.cache_clear()` before/after app creation to prevent state leaks.
