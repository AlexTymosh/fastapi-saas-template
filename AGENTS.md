# AGENTS.md

## Purpose

Execution contract for AI coding agents. Enforce architecture, constraints, and patterns. Prefer consistency over creativity.

## Instruction Priority

1. User task.
2. This file.
3. Existing repository patterns.
4. README.
5. Framework defaults.

## Before starting work

Codex/AI agents must:

1. Confirm current working directory and branch.
2. Read `AGENTS.md`.
3. Read `SESSION_NOTES.md` if present.
4. Read relevant docs from `backend/docs`.
5. Run `git status`.
6. Report the plan before editing.

## Structure

The backend is a modular monolith with explicit layers:

- `api`
- `services`
- `repositories`
- `schemas`
- `models`
- `core`

Domain modules live under:

```text
backend/app/<domain>/
  api/
  services/
  repositories/
  schemas/
  models/
```

Router registration entry point:

```text
backend/app/api/master_router.py
```

Expected flow:

`HTTP -> API -> Service -> Repository -> Service -> Response`

## Router contract

- Domain router files live in `backend/app/<domain>/api/*.py`.
- One file defines one router.
- Each router must define tags.
- Route paths must be defined inside domain router files.
- Routers should be attached in deterministic order with numbered comments when practical.
- `backend/app/api/master_router.py` is the only domain-router registration point.
- All API routes are attached to `v1_router`.
- Version prefix `/api/v1` is applied centrally in `master_router.py` through settings.
- `main.py` must not register domain routers directly.
- Do not pass extra prefixes in `include_router`, except the central version prefix.

## Layer responsibilities

- API handlers must stay thin.
- API must not contain business logic.
- Services contain business logic, orchestration, and authorization decisions.
- Repositories handle database access only.
- API layer must not access the database directly.
- Do not use raw SQL outside repositories unless explicitly justified.
- Use FastAPI dependency injection with `Depends`; avoid hidden globals.
- Use async only for database/external I/O; pure CPU logic should be sync.

## API response contract

- Single resource: clean REST response.
- Collections: `{ "data": [], "meta": {}, "links": {} }`.
- Errors: Problem Details style with `application/problem+json`.
- Operational endpoints may return endpoint-specific payloads.

## Error handling contract

- API layer must not format business errors manually.
- API layer must not use `try`/`except` for business-flow errors.
- Services raise application/domain exceptions.
- Global FastAPI handlers format Problem Details responses.
- Do not leak internals, stack traces, tokens, secrets, or raw sensitive data.

## Security and auth

- JWT authentication uses Keycloak as identity provider.
- Authentication and authorization are separate concerns.
- Tenant authorization is resolved from local database memberships.
- Platform authorization is resolved from `platform_staff`.
- Permission logic belongs in services/dependencies, not arbitrary API code.
- Platform write endpoints must use the platform write rate limiting dependency/policy; do not add new platform write endpoints without rate limiting.
- Do not trust client-provided identifiers, roles, or permissions.
- Do not implement local password login unless explicitly requested.

## Logging

- Use structured JSON logging when configured.
- Never log passwords, tokens, API keys, or raw personal data such as email/IP.
- Logs must redact tokens, passwords, secrets, cookies, authorization headers, and API keys across common key variants.
- Mask or hash identifiers when needed.

## Configuration

- Use environment-based configuration only.
- Do not hardcode secrets, credentials, or deployment URLs.
- Keep local defaults safe for development.

## Testing

- Tests live under `backend/tests`.
- Levels: unit, integration, e2e, contract.
- Test business logic in services.
- Mock external dependencies in unit tests.
- Cover API behaviour with integration/e2e tests.
- Before running pytest in a fresh environment, install dev dependencies from `backend/`:
  `python -m pip install -e ".[dev]"`.
- If editable install is unavailable, use:
  `python -m pip install -r requirements-dev.txt`.
- Recommended test bootstrap:

```bash
cd backend
python -m pip install -e ".[dev]"
pytest -q -m "not external_db"
- Prefer `pytest -q -m "not external_db"` for broad safe checks.
- Documentation-only changes should run grep/link sanity checks.

## Change rules

- Read existing code before changing behaviour.
- Follow existing project patterns.
- Make the minimal necessary changes.
- Update tests and docs when behaviour changes.
- Do not change backend code for documentation-only tasks.
- Do not commit or push without explicit instruction from the controlling task.

## Forbidden

- Business logic in API handlers.
- Database access outside repositories.
- Logging sensitive data.
- Hardcoded secrets.
- Unnecessary new frameworks.
- Over-abstraction.
- Catch-all `utils`/`helpers` modules without narrow scope.
- Exposing ORM models directly as API responses.
- Unjustified try/except blocks around imports. Optional dependency/version compatibility fallbacks are allowed only when documented and tested.

## Source of truth

1. Code is primary source of truth.
2. `AGENTS.md` controls AI-agent workflow.
3. `backend/docs/architecture.md` controls architecture docs.
4. `backend/docs/current-state.md` controls current status.
5. `SESSION_NOTES.md` controls live handoff state.
6. Feature-specific docs control details only for their area.