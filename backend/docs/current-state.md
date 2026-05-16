# Current State

## Last Updated

2026-05-16

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
- Platform staff, permissions, current platform identity endpoint foundation, full platform list filters, limited platform user/organisation/audit views, and OpenAPI operation ID hardening for future generated admin clients.
- Audit events foundation, including a backend-redacted limited platform audit view.
- Outbox foundation.
- Redis/rate limiting foundation, including route-level dependency policies, settings-aware effective policy resolution, authenticated reads, tenant read/write/create flows, layered invite anti-abuse flows, platform read/audit reads, fail-closed platform write policies, and versioned HMAC-SHA256 identifier bucket keys backed by a dedicated rate-limit secret.
- Observability/OpenTelemetry foundation.
- pytest/Testcontainers foundation.
- `uv` dependency workflow:
  - `.python-version` pins Python 3.12;
  - `backend/pyproject.toml` uses `[dependency-groups].dev`;
  - `backend/uv.lock` is the only dependency lock source;
  - `Taskfile.yml` wraps common `uv run` checks;
  - `.pre-commit-config.yaml` uses local `uv` hooks;
  - GitHub Actions CI runs the backend quality gate with `uv`;
  - Docker backend image installs runtime dependencies from `uv.lock` with `uv sync --frozen --no-dev --no-editable`.

## Partially Implemented

- GDPR/privacy posture.
- Production hardening.
- Platform workflows, including explicit platform visibility for soft-deleted organisations in admin operations while tenant organisation endpoints keep excluding deleted organisations by default.
- Organisation soft deletion preserves the original slug, while database-level active-only uniqueness allows slug reuse after deletion without allowing duplicate active slugs.
- Invite delivery pipeline.
- Observability integration.
- Full contract/security test coverage beyond the current platform OpenAPI client contract, full-list filter tests, and platform permission matrix tests.

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
- Production Docker/runtime hardening is not complete beyond the current `uv`-based runtime dependency install.
- CORS policy is implemented as an explicit environment-driven allowlist and is disabled by default.
- CI should remain required and green before merging protected branches.
- Access-control tests need continuous expansion; platform OpenAPI route-name operation ID checks, platform tag checks, typed response-model checks, full-list filter tests, permission matrix, and limited field-authorisation coverage are present for current platform endpoints.
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
- `README.md`, `AGENTS.md`, and `Taskfile.yml` are the primary developer workflow entry points.

## Testing Status

For local development, install dependencies through `uv`:

```bash
cd backend
uv sync --group dev
```

Preferred checks from the repository root:

```bash
task lint
task test:safe
task test:security
task test:contracts
task ci
```

Direct strict CI-equivalent checks from `backend/`:

```bash
uv lock --check
uv sync --frozen --group dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen pytest -q -m "not external_db"
uv run --frozen pytest -q -m "security and not external_db"
uv run --frozen pytest -q tests/contracts
```

External DB tests are opt-in and must not run by default.

## Dependency Management Status

- Do not use Poetry.
- Do not use `pip-tools`.
- Do not recreate `requirements.txt` or `requirements-dev.txt`.
- `backend/uv.lock` is the single dependency lock source.
- Runtime Docker dependency installation is based on `uv sync --frozen --no-dev --no-editable`.

## Recommended Next Steps

1. Keep CI green and required before merging.
2. Continue expanding BOLA/BFLA and platform permission tests.
3. Harden Docker/runtime for production beyond dependency installation, especially non-root runtime and deployment-specific hardening.
4. Continue trusted proxy policy hardening and verify deployment-specific CORS origins.
5. Continue feature-specific docs only after code stabilises.

## Source of Truth

1. Code is primary source of truth.
2. `AGENTS.md` controls AI-agent workflow.
3. `backend/docs/architecture.md` controls architecture docs.
4. `backend/docs/current-state.md` controls current status.
5. `SESSION_NOTES.md` controls live handoff state.
6. Feature-specific docs control details only for their area.
