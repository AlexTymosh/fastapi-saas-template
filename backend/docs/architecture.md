# Architecture

## Status

This document is the canonical architecture source of truth for the current FastAPI SaaS Template stage. The project is in active development and is not production-ready.

Documentation can lag implementation. When this document conflicts with code, the actual code wins and this document must be updated.

## Project Overview

FastAPI SaaS Template is a backend-only FastAPI SaaS backend template built as a modular monolith. It targets small and medium SaaS products and lightweight marketplace or two-sided scenarios where a single backend can own tenant, membership, invite, platform, audit, outbox, rate limiting, and observability foundations.

The repository does not contain a frontend application. It is intended as a backend foundation that can be extended by product-specific applications.

## Repository Scope

The repository scope is the backend application, local development support, migrations, tests, and documentation. Product-specific frontend code, production infrastructure, and organisation-specific deployment policy are outside the current repository scope unless added explicitly.

## Backend Architecture

The backend follows a modular-monolith structure with explicit layers:

`HTTP -> API -> Service -> Repository -> Service -> Response`

Layer responsibilities:

- API: FastAPI routers, dependency wiring, request/response schemas, and thin endpoint handlers.
- Services: business logic, orchestration, authorization decisions, and application/domain exceptions.
- Repositories: database access only.
- Schemas: Pydantic request/response contracts and collection envelopes.
- Models: SQLAlchemy ORM models.
- Core: cross-cutting infrastructure such as configuration, database, authentication, errors, logging, middleware, observability, Redis, rate limiting, secrets, and task setup.

### Persistence Ownership

Domain repositories own persistence for their aggregate tables. Application and platform services may orchestrate workflows across repositories, but they must not duplicate basic persistence access for domain-owned tables or leak SQLAlchemy query construction into orchestration code.

Ownership rules:

- `users` table -> `UserRepository`
- `organisations` table -> `OrganisationRepository`
- `memberships` table -> `MembershipRepository`
- `platform_staff` table -> `PlatformStaffRepository`

Platform services may call domain repositories and platform-owned repositories for privileged workflows. Platform repositories are limited to platform-owned tables, such as `platform_staff`, or explicit platform read/reporting models that intentionally span multiple aggregates. Platform services remain responsible for permission-aware workflows, state-transition decisions, audit event creation, and conflict/not-found mapping.

### Transaction Ownership

Repositories may use `flush()` and `refresh()` to make changes visible within the current unit of work, but they must not call `commit()` or `rollback()`. Application services should not commit by default; they should orchestrate business rules, repository calls, and audit writes inside a transaction provided by the caller.

Write API dependencies own transaction boundaries with `async with session.begin()` after authentication and rate limiting have completed. Read endpoints use the lazy request-scoped session and should not open explicit transactions unless a specific consistency requirement justifies it. CLI commands and background workers must create their own explicit transaction boundaries.

Global transaction middleware is intentionally avoided because it can start database work too early, weaken early authentication/rate-limit short-circuiting, and hide transaction scope.

## Application Skeleton

Current application skeleton:

```text
backend/app/
  api/
    master_router.py

  <domain>/
    api/
    services/
    repositories/
    schemas/
    models/

  core/
    ...
```

Current and expected domain module examples include:

- `users`
- `organisations`
- `memberships`
- `invites`
- `platform`
- `audit`
- `outbox`
- `health`

Some domains may not use every layer yet. For example, health endpoints do not need database models.

## API Routing Contract

- Domain routers live in `backend/app/<domain>/api/*.py`.
- One router file defines one router.
- `backend/app/api/master_router.py` is the only domain-router registration point.
- `main.py` must not register domain routers directly.
- All API routes are attached to the versioned router built by `master_router.py`.
- The `/api/v1` version prefix is applied centrally through settings and `master_router.py`.
- Route paths are defined inside domain router files.
- Routers must define tags.
- Deterministic router ordering is preferred and should be documented with numbered comments when practical.
- `include_router` calls should not pass extra prefixes except the central version prefix.

## API Response Contract

- Single resources use clean REST responses without an artificial envelope.
- Collections use an envelope:

```json
{
  "data": [],
  "meta": {},
  "links": {}
}
```

- Errors use Problem Details style responses with `application/problem+json`.
- Operational endpoints, such as health and readiness, may return endpoint-specific payloads.

## Error Handling Contract

- API handlers must not contain business-error formatting logic.
- Services raise application/domain exceptions.
- FastAPI global exception handlers format errors as Problem Details.
- Error payloads must not expose internal details, stack traces, secrets, tokens, or raw sensitive data.

## Authentication

- Keycloak is the identity provider and JWT issuer.
- FastAPI acts as an OAuth2 Resource Server and validates Keycloak access tokens when authentication is enabled.
- JWT validation checks RS256 signature, issuer, audience, expiry, issued-at, subject, `kid`, authorised party (`azp`) when configured, and maximum token lifetime.
- Startup OIDC metadata validation verifies issuer/discovery/JWKS shape when enabled and must fail closed in staging/prod.
- JWKS key-rotation refresh is cached and protected by a forced-refresh cooldown/singleflight guard.
- The local user projection links Keycloak users with application users using `external_auth_id == sub`.
- The backend does not implement local password login.
- The backend does not duplicate Keycloak email verification.
- The detailed identity contract is documented in `backend/docs/keycloak-identity-contract.md`.

## Tenant Authorization

- Tenant authorization is based on local database memberships.
- Relevant models include `organisations`, `memberships`, and `users`.
- Tenant roles are:
  - `owner`
  - `admin`
  - `member`
- One user can have at most one active organisation membership.
- Each active organisation must have exactly one active owner.
- Soft-deleted organisations may have their memberships deactivated as part of the deletion flow.
- The `owner` role cannot be assigned through the tenant invite flow.
- Tenant roles must not be trusted from arbitrary client input or JWT claims. External IdP roles may only be considered in the future as input for controlled, idempotent, audited JIT provisioning that writes local membership records before permissions are granted.

## Platform Authorization

- Platform authorization is based on `platform_staff`.
- Platform roles and permissions are resolved from the database. External IdP roles from direct `roles`, `realm_access`, `resource_access`, or similar claims must never grant request-time platform permissions.
- Platform access is separated from tenant access.
- Tenant endpoints must not include a global-administrator bypass.
- Platform endpoints live under `/api/v1/platform/*`. Future IdP-role-based JIT provisioning, if added, must write local `platform_staff` records before platform permissions are granted.

## Data Model Overview

Current core data model areas:

- Users: local projection of authenticated Keycloak users.
- Organisations: tenant/business entities.
- Memberships: local tenant access records and roles.
- Invites: tenant invitation lifecycle.
- Platform staff: platform-level access control.
- Audit events: separate audit records for sensitive actions.
- Outbox events: durable foundation for asynchronous side effects.

The database schema is managed through Alembic migrations. Model details must be verified against code and migrations before changing contracts.

## Rate Limiting

- Canonical document: `backend/docs/rate-limiting.md`.
- Rate limiting is Redis-backed and route-level dependency-based rather than middleware-based.
- It is disabled by default and enabled through settings.
- Effective policies are resolved from declarative specs, selected mode, and per-policy overrides during startup.
- The protected endpoint matrix, policy defaults, fail-open/fail-closed behaviour, panic mode, and Retry-After contract are defined in the canonical rate-limiting document.

## Outbox and Background Jobs

- Dramatiq is used for background jobs.
- The outbox pattern foundation exists.
- Invite delivery is published through outbox events.
- Invite raw tokens are not stored directly in invite records.
- An encrypted raw token may exist in an outbox payload for delivery.

## Audit Logging

- Audit events are stored separately from business records.
- Audit metadata must not contain tokens, secrets, or raw credentials.
- Audit context may include actor, IP, and user-agent data.
- Limited platform audit views must expose only safe summary fields and must not expose raw metadata, IP addresses, user-agent strings, free-text reasons, or direct actor identifiers.
- Retention, GDPR erasure/export, and masking policy still need project-specific production hardening.

## Observability

- An observability foundation exists.
- OpenTelemetry metrics support is present.
- The OTLP exporter is optional and configurable.
- Prometheus and Grafana are not part of the current phase unless implemented later.
- A `/metrics` endpoint is not exposed unless implemented later.
- Detailed observability notes are documented in `backend/docs/observability.md`.

## Configuration

- Configuration is environment-driven via Pydantic settings.
- Secrets and credentials must not be hardcoded.
- Authentication, Redis, rate limiting, observability, database, logging, request-context, Vault, and outbox behaviour are configured through settings.
- Production deployments must provide explicit environment values and secret management.

## Testing Strategy

- Tests use `pytest`.
- Test direction includes unit, integration, e2e, and contract coverage.
- Testcontainers are used for integration/e2e infrastructure where needed.
- External persistent database tests are opt-in.
- Safe command for broad local checks:

```bash
pytest -q -m "not external_db"
```

- Documentation-only changes should at least run grep/link sanity checks.
- Detailed e2e/integration conventions are documented in `backend/docs/testing-e2e.md`.

## Security and GDPR Notes

- Authentication and authorization are separate concerns.
- Tenant and platform roles are resolved from local database state, not arbitrary client input.
- Logs must not contain passwords, tokens, API keys, raw email addresses, raw IP addresses, or other unnecessary personal data.
- Audit and observability metadata must be reviewed before production use.
- GDPR/privacy posture exists as a foundation but still requires project-specific hardening.

## Known Limitations

- The project is in active development.
- Documentation can lag code.
- Production hardening is incomplete.
- CI status must be verified separately.
- Not all planned GDPR/security features are complete.
- Observability integration should be verified in the target deployment environment.
- Access-control and contract test coverage must continue to expand as features stabilise.

## Source of Truth Rules

1. Actual code is the primary source of truth.
2. `AGENTS.md` defines AI-agent working rules.
3. `backend/docs/architecture.md` defines architectural source of truth.
4. `backend/docs/current-state.md` defines current project state.
5. `SESSION_NOTES.md` defines live handoff context.
6. Feature-specific docs define details only for their area.