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
- Python 3.12 for local backend development.
- `uv` for Python dependency management.
- Task for the project command runner.

The repository pins the local Python version in `.python-version`.

### Run locally with Docker Compose

`compose.yaml` is a **local development stack only**. It is not a production deployment manifest.
The default stack does not run database migrations automatically and does not start Vault.

```bash
cp .env.example .env
docker compose up --build -d postgres redis keycloak
docker compose run --rm migrate
docker compose up --build -d app worker outbox-dispatcher
```

For later local starts:

```bash
docker compose up -d
docker compose run --rm migrate
```

Run migrations explicitly after a fresh database setup or after schema changes:

```bash
docker compose run --rm migrate
```

The local migration service runs as a one-shot Compose tool and exits after `alembic upgrade head`.

### Optional local Vault dev profile

Vault is disabled by default. The local Vault service is a dev/demo integration profile, not a production secret store.

```bash
docker compose --profile vault up -d vault vault-init
```

Do not reuse the local Vault dev token in staging or production.

### Health checks

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

## Local Backend Development

Install backend development dependencies from the lockfile:

```bash
cd backend
uv sync --group dev
```

Use Taskfile commands from the repository root for normal development:

```bash
task lint
task test:lightweight
task test:safe
task test:security
task test:authz
task test:privacy
task test:contracts
task ci
```

Direct backend commands should use `uv run` from `backend/`:

```bash
cd backend
uv run pytest -q -m "not external_db"
uv run ruff check .
uv run ruff format --check .
```

Do not use `pip-tools`, `requirements.txt`, or `requirements-dev.txt`.
`backend/uv.lock` is the single dependency lock source.

## Local Services

When started via Compose, the core local stack includes:

- API service.
- PostgreSQL.
- Redis.
- Keycloak for local identity flows.
- Dramatiq worker.
- Outbox dispatcher.

Optional local profiles include:

- Vault dev/demo profile: `docker compose --profile vault up -d vault vault-init`.
- OTel Collector profile: `docker compose --profile observability up -d otel-collector`.

See `compose.yaml` for the exact runtime composition.

## Configuration and Secrets

The project uses granular environment variables. `APP__ENVIRONMENT` is a validation/safety mode, not a hidden config selector.

- `.env.example` contains local-only placeholders and should be copied to `.env` for local work.
- `.env` must not be committed.
- Staging and production secrets must come from the deployment platform, Vault, or another secret manager.
- Docker Compose local service credentials such as `POSTGRES_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, and `VAULT_DEV_ROOT_TOKEN_ID` are local placeholders only.
- Compose builds container-internal database URLs from `POSTGRES_*` variables so containers connect to the `postgres` service hostname.
- Host-local development can keep using `DATABASE__URL` with `localhost`.

See `backend/docs/configuration.md` for the detailed configuration model.

## Authentication / Keycloak

Keycloak is the identity provider and JWT issuer.

- FastAPI acts as an OAuth2 Resource Server and validates Keycloak access tokens for this API.
- Production validation requires issuer, API audience, allowed authorised parties (`azp`), strict claim validation, and startup OIDC metadata validation.
- Local user projection uses `external_auth_id == sub`.
- Tenant roles are resolved from database memberships.
- Platform roles and permissions are resolved from `platform_staff`.
- Sensitive authenticated endpoint groups use explicit endpoint-level Redis-backed rate limiting: authenticated reads, tenant read/write/create flows, invite create/accept/mutation flows, platform read/audit reads, and fail-closed platform writes (`platform_write` / `platform_staff_write`). When app-level rate limiting is enabled, set a dedicated `RATE_LIMITING__IDENTIFIER_SECRET` (for example generated with `openssl rand -hex 32`) so Redis bucket keys use versioned HMAC-SHA256 identifiers instead of raw user/IP values.
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

Preferred local commands from the repository root:

```bash
task test:lightweight
task test:safe
task test:security
task test:authz
task test:privacy
task test:contracts
task ci
```

Equivalent broad safe command from `backend/`:

```bash
uv run pytest -q -m "not external_db"
```

Focused marker or folder selections are available for local diagnosis, but they are not mandatory duplicate CI gates. Security regression suites are explicitly marked and can be collected or run independently:

```bash
uv run pytest -q -m "security and not external_db" --collect-only
uv run pytest -q -m "security and not external_db"
uv run pytest -q -m "authz and not external_db"
uv run pytest -q -m "privacy and not external_db"
uv run pytest -q tests/rate_limit
uv run pytest -q tests/audit
uv run pytest -q tests/logging
```

External DB tests are opt-in:

```bash
uv run pytest -q -m external_db --run-external-db -rs
```

External DB tests also require the documented environment flags. See `backend/docs/testing-e2e.md` for integration/e2e conventions.

## CI

GitHub Actions runs the backend quality gate on pull requests and pushes to `main`.

The workflow uses:

- `.python-version` for Python 3.12;
- `uv lock --check`;
- `uv sync --frozen --group dev`;
- Ruff formatting and lint checks;
- one broad non-external-db pytest run: `uv run --frozen pytest -q -m "not external_db"`;
- an aggregate `CI status` job that is safe to require in branch protection and passes for docs-only changes when the backend quality gate is skipped.

Local equivalent:

```bash
task ci
```

## Deployment and migrations

This repository does not currently provide a production deployment manifest.

For local Docker Compose, database migrations are explicit:

```bash
docker compose run --rm migrate
```

For staging and production, migrations should be run as a separate deployment/release step using the same application image and the real deployment `DATABASE__URL`.

Do not run migrations implicitly inside every application container startup.

## Documentation

Start here:

- Architecture source of truth: `backend/docs/architecture.md`.
- Current project state: `backend/docs/current-state.md`.
- Configuration and local Compose boundaries: `backend/docs/configuration.md`.
- Rate limiting: `backend/docs/rate-limiting.md`.
- Keycloak identity contract: `backend/docs/keycloak-identity-contract.md`.
- Keycloak production setup: `backend/docs/auth/keycloak-production-setup.md`.
- Observability: `backend/docs/observability.md`.
- E2E and integration testing: `backend/docs/testing-e2e.md`.

## Development Notes

- Keep API handlers thin; business logic belongs in services.
- Repositories are the only database access layer.
- Router registration is centralised in `backend/app/api/master_router.py`.
- Use environment-driven configuration; never commit secrets.
- Use `uv` and Taskfile commands for backend dependency, lint, and test workflows.
- Read `AGENTS.md` before AI-agent or Codex work.
- Grouped business bucket checks execute atomically via Redis Lua in Redis-backed mode; grouped keys use a shared Redis Cluster hash tag and fall back to the compatibility path only if Redis reports CROSSSLOT, MOVED, ASK, CLUSTERDOWN, TRYAGAIN, or related cluster routing errors.
