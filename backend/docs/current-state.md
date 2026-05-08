# Current State

## Last Updated

2026-05-06

## Project Phase

Active development. The repository provides a backend-only FastAPI SaaS template foundation and is not production-ready.

## Implemented

The following foundations are present in code and/or current documentation and should be verified against code before extension:

- FastAPI app factory and lifespan.
- Central master router.
- Health endpoints.
- SQLAlchemy async foundation.
- Alembic migrations foundation.
- Keycloak JWT validation foundation.
- Local user projection with `external_auth_id`.
- Organisations, memberships, and invites foundation.
- Platform staff and permissions foundation.
- Audit events foundation, including a backend-redacted limited platform audit view.
- Outbox foundation.
- Redis/rate limiting foundation, including route-level dependency policies, settings-aware effective policy resolution, config-level strict/relaxed/panic modes, authenticated reads, tenant read/write/create flows, invite flows, platform read/audit reads, and fail-closed platform write policies.
- Observability/OpenTelemetry foundation.
- pytest/Testcontainers foundation.

## Partially Implemented

- GDPR/privacy posture.
- Production hardening.
- Platform workflows.
- Invite delivery pipeline.
- Observability integration.
- Full contract/security test coverage.

## Not Implemented / Planned

The following areas should not be presented as complete without code verification:

- Production-grade deployment hardening.
- Complete GDPR export/erasure workflows for every data area.
- Complete platform operations workflows.
- Full BOLA/BFLA security test matrix.
- Prometheus/Grafana stack or `/metrics` endpoint, unless added later.
- Frontend application.

## Known Risks

- Documentation may lag code.
- Production Docker/runtime hardening is not complete.
- CORS policy is implemented as an explicit environment-driven allowlist and is disabled by default.
- CI status must be verified.
- Access-control tests need continuous expansion.
- Deleted or renamed docs must not leave broken links.
- Documentation must not claim planned features as implemented.

## Documentation Status

- `backend/docs/architecture.md` is the canonical architecture document.
- `backend/docs/rate-limiting.md` is the only canonical rate-limiting document.
- `backend/docs/keycloak-identity-contract.md` contains the detailed identity contract.
- `backend/docs/observability.md` contains observability details.
- `backend/docs/testing-e2e.md` contains integration/e2e testing conventions.
- `SESSION_NOTES.md` contains short live handoff notes for AI-agent sessions.

## Testing Status

Backend tests were not run for this documentation alignment. For code changes, use the test strategy in `backend/docs/testing-e2e.md` and prefer:

```bash
pytest -q -m "not external_db"
```

External DB tests are opt-in and must not run by default.

## Recommended Next Steps

1. Complete docs alignment.
2. Add or verify CI.
3. Add BOLA/BFLA tests.
4. Harden Docker/runtime for production.
5. Continue hardening trusted proxy policy and verify deployment-specific CORS origins.
6. Continue feature-specific docs only after code stabilises.

## Source of Truth

1. Code is the primary source of truth.
2. `AGENTS.md` controls AI-agent workflow.
3. `backend/docs/architecture.md` controls architecture docs.
4. `backend/docs/current-state.md` controls current status.
5. `SESSION_NOTES.md` controls live handoff state.
6. Feature-specific docs control details only for their feature area.