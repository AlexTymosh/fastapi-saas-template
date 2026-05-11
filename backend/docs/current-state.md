# Current State

## Last Updated

2026-05-11

## Project Phase

Active development. The repository provides a backend-only FastAPI SaaS template foundation and is not production-ready.

## Implemented

The following foundations are present in code and/or current documentation and should be verified against code before extension:

- FastAPI app factory and lifespan.
- Central master router.
- Health endpoints.
- SQLAlchemy async foundation.
- Alembic migrations foundation.
- Keycloak JWT validation hardened for OAuth2 Resource Server access tokens, including strict issuer/audience/`azp`/`iat`/`kid`/lifetime checks, startup OIDC metadata validation, and JWKS forced refresh cooldown/singleflight protection.
- Local user projection with `external_auth_id`.
- Organisations, memberships, and invites foundation.
- Platform staff, permissions, current platform identity endpoint foundation, offline first-admin bootstrap CLI, full platform list filters, and limited platform user/organisation/audit views for future admin frontend clients.
- Audit events foundation, including a backend-redacted limited platform audit view.
- Outbox foundation.
- Redis/rate limiting foundation, including route-level dependency policies, settings-aware effective policy resolution, authenticated reads, tenant read/write/create flows, layered invite anti-abuse flows, platform read/audit reads, fail-closed platform write policies, and versioned HMAC-SHA256 identifier bucket keys backed by a dedicated rate-limit secret.
- Observability/OpenTelemetry foundation.
- pytest/Testcontainers foundation.

## Partially Implemented

- GDPR/privacy posture.
- Production hardening.
- Platform workflows, including explicit platform visibility for soft-deleted organisations in admin operations while tenant organisation endpoints keep excluding deleted organisations by default.
- Organisation soft deletion preserves the original slug, while database-level active-only uniqueness allows slug reuse after deletion without allowing duplicate active slugs.
- Invite delivery pipeline.
- Observability integration.
- Full contract/security test coverage beyond the current platform OpenAPI contract, exact platform operation ID checks, full-list filter tests, and platform permission matrix tests.

## Not Implemented / Planned

The following areas should not be presented as complete without code verification:

- Production-grade deployment hardening.
- Complete GDPR export/erasure workflows for every data area.
- Complete platform operations workflows.
- Full BOLA/BFLA security test matrix outside the currently covered tenant BOLA and platform permission-matrix slices.
- Prometheus/Grafana stack or `/metrics` endpoint, unless added later.
- Frontend application.

## Known Risks

- Documentation may lag code.
- Soft-deleted organisations are operational/audit records: platform admin workflows may request explicit visibility for support, compliance, audit, or recovery, but tenant APIs must not accidentally expose them.
- Production Docker/runtime hardening is not complete.
- CORS policy is implemented as an explicit environment-driven allowlist and is disabled by default.
- CI status must be verified.
- Access-control tests need continuous expansion; platform OpenAPI contract, exact operation ID checks, full-list filter tests, permission matrix, and limited field-authorisation coverage are present for current platform endpoints.
- Deleted or renamed docs must not leave broken links.
- Documentation must not claim planned features as implemented.

## Documentation Status

- `backend/docs/architecture.md` is the canonical architecture document.
- `backend/docs/rate-limiting.md` is the only canonical rate-limiting document.
- `backend/docs/keycloak-identity-contract.md` contains the detailed identity contract.
- `backend/docs/observability.md` contains observability details.
- `backend/docs/testing-e2e.md` contains integration/e2e testing conventions.
- `backend/docs/access-control/en` is the canonical access-control documentation source.
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