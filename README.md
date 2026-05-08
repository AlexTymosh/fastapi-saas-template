# FastAPI SaaS Template

## Status

🏗️ This project is in active development and is **not production-ready**.

## Project Overview

FastAPI SaaS Template is a backend-only FastAPI SaaS backend template built as a modular monolith.

- Backend-only repository; no frontend application is included.
- Identity is delegated to Keycloak using OIDC/JWT.
- Tenant and platform access are stored in the application database.
- Intended for small/medium SaaS products and lightweight marketplace or two-sided scenarios.

## Architecture

High-level flow:

`HTTP -> API -> Service -> Repository -> Service -> Response`

Core layout:

- `backend/app/api/master_router.py` — central API router composition and version prefix wiring.
- `backend/app/<domain>/api/` — domain routers.
- `backend/app/<domain>/services/` — business logic and orchestration.
- `backend/app/<domain>/repositories/` — database access.
- `backend/app/<domain>/schemas/` — Pydantic request/response contracts.
- `backend/app/<domain>/models/` — SQLAlchemy ORM models.

Canonical architecture details are in `backend/docs/architecture.md`.
Current project state is tracked in `backend/docs/current-state.md`.

## Quick Start

### Requirements

- Docker Desktop / Docker Engine with Docker Compose v2.
- Git.

### Run locally

```bash
cp .env.example .env
docker compose up --build -d
```

### Apply migrations

```bash
docker compose exec app python -m alembic upgrade head
```

### Health checks

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

## Local Services

When started via Compose, the core local stack includes:

- API service.
- PostgreSQL.
- Redis.
- Keycloak for local identity flows.
- Additional local services may include Dramatiq worker, outbox dispatcher, Vault dev service, and optional OTel Collector profile. See `compose.yaml` for the exact runtime composition.

## Authentication / Keycloak

Keycloak is the identity provider and JWT issuer.

- FastAPI validates JWTs.
- Local user projection uses `external_auth_id == sub`.
- Tenant roles are resolved from database memberships.
- Platform roles and permissions are resolved from `platform_staff`.
- Sensitive authenticated endpoint groups use route-level dependency-based Redis-backed rate limiting with settings-aware effective policies: authenticated reads, tenant read/write/create flows, invite create/accept/mutation flows, platform read/audit reads, and fail-closed platform writes (`platform_write` / `platform_staff_write`).
- Limited platform audit access uses a backend redacted endpoint that omits raw metadata, IP address, user-agent, free-text reason, and direct actor identifiers.
- The detailed identity contract is in `backend/docs/keycloak-identity-contract.md`.


## Browser CORS

CORS is disabled by default. For a local browser frontend, enable it explicitly in `.env` and keep allowed origins as a concrete allowlist, for example:

```bash
CORS__ENABLED=true
CORS__ALLOW_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

Do not combine wildcard origins with credentials. Production deployments must use explicit frontend origins.

## Testing

From `backend/`:

```bash
pip install -e ".[dev]"
pytest -q
```

Safe broad suite:

```bash
pytest -q -m "not external_db"
```

Security regression suites are explicitly marked and can be collected or run independently:

```bash
pytest -q -m "security and not external_db" --collect-only
pytest -q -m "security and not external_db"
pytest -q -m "security and integration"
pytest -q -m bola
pytest -q -m rate_limit
```

External DB tests are opt-in. See `backend/docs/testing-e2e.md` for integration/e2e conventions.

## Documentation

Start here:

- Architecture source of truth: `backend/docs/architecture.md`.
- Current project state: `backend/docs/current-state.md`.
- Rate limiting: `backend/docs/rate-limiting.md`.
- Keycloak identity contract: `backend/docs/keycloak-identity-contract.md`.
- Observability: `backend/docs/observability.md`.
- E2E and integration testing: `backend/docs/testing-e2e.md`.

## Development Notes

- Keep API handlers thin; business logic belongs in services.
- Repositories are the only database access layer.
- Router registration is centralised in `backend/app/api/master_router.py`.
- Use environment-driven configuration; never commit secrets.
- Read `AGENTS.md` before AI-agent or Codex work.