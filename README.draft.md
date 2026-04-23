# README draft

## Status
Work in progress

## Contents
- [Project Overview](#project-overview)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [API Standards](#api-standards)
- [Authentication](#authentication)
- [Authorization (RBAC)](#authorization-rbac)
- [Logging. General concept](#logging-general-concept)
- [Metrics and tracing](#metrics-and-tracing)
- [Security](#security)
- [Data & GDPR](#data--gdpr)
- [PostgreSQL, SQLAlchemy](#postgresql-sqlalchemy)
- [Backup Strategy](#backup-strategy)
- [Code Style](#code-style)
- [Testing](#testing)
- [Documentation](#documentation)

## Project Overview
The system is a FastAPI backend template with a **modular monolith** architecture, with the ability to easily build projects on this base under GDPR requirements.

The template is designed for building small and medium SaaS systems, including lightweight marketplace scenarios and two-sided platforms (for example, client–contractor, customer–supplier), without introducing infrastructure intended for large distributed platforms or high-scale ecosystems. The architecture remains minimalistic at the core level, but allows extension with domain modules and business logic.

API Response Standard is used, with one exception: API responses for data collections are sent in an envelope with pagination.

### Expected clients
- desktop PCs
- tablets
- mobile devices

System is designed to handle up to 1000 RPS under the following conditions:
- p95 latency target: < 200 ms
- 70% read / 30% write workload
- single instance baseline: 4 vCPU / 8 GB RAM
- average response payload < 10 KB
- PostgreSQL with indexed queries
- synchronous audit logging enabled
- JWT validation via cached Keycloak JWKS

Final metrics directly depend on specific modifications and must be validated before and after receiving the technical specification.

## Configuration
Application configuration must be environment-based.

- Environment variables are the primary configuration source
- Secrets must be stored in Vault (not in code or .env files in production)
- Separate configurations must be defined for dev / staging / production

### Planned stack
**Backend framework:** FastAPI
**Secret storage:** HashiCorp Vault
**IAM:** Keycloak
**Database:** Async PostgreSQL
**Admin panel:** SQLAdmin
**Migration:** Alembic
**ORM:** SQLAlchemy (async)
**Validation:** Pydantic
**Broker, cache:** REDIS
**Background task:** Dramatiq
**Build:** Docker Compose

### Preconfigured operators (with the ability to switch easily to other operators)
SMS provider: TWILIO
Email service: SendGrid
Backups: Cloudflare R2

## Development Setup

1.  Clone repository

``` bash
git clone <your-repo-url>
cd fastapi-saas-template
```

2.  Create virtual environment

``` bash
python -m venv .venv
```

Activate (Windows PowerShell):

``` bash
.venv\Scripts\Activate.ps1
```

3.  Upgrade pip (recommended)

``` bash
python -m pip install --upgrade pip
```

4.  Install the backend package with development extras

``` bash
pip install -e "backend[dev]"
```

5.  Setup pre-commit hooks

``` bash
pre-commit install
```

Pre-commit hooks will automatically run linting and formatting checks
before each commit.

------------------------------------------------------------------------

Dependency and tooling configuration is defined in `backend/pyproject.toml`.
Development tools are declared as optional dependencies under
`[project.optional-dependencies].dev`.

## Quick Start
The template is designed to be run via Docker Compose.

Detailed setup instructions will be provided once the base infrastructure
configuration is finalized.


## API Standards

### Versioning and router connection
All routers are connected via `master_router` and initially use the versioning prefix `/api/v1`.

### API Responses
#### 1. Single Resource Response
Clean REST.
Example:

```json
{
  "id": "123",
  "name": "Example"
}
```

#### 2. Collection Response
Standardized and includes:
- data
- meta (page, pageSize, total)
- links (next)

Example:

```json
{
  "data": [
    { "id": 1 },
    { "id": 2 }
  ],
  "meta": {
    "page": 1,
    "pageSize": 20,
    "total": 999
  },
  "links": {
    "next": "/resources?page=2"
  }
}
```

#### 3. Error Response
- RFC 9457 Problem Details style is used with project-specific extensions:
  - `error_code`
  - `request_id`
  - `errors`
  
Example:

```json
{
  "type": "problem:validation-error",
  "title": "Validation Error",
  "status": 400,
  "detail": "Email is invalid",
  "instance": "/users",
  "error_code": "validation_error",
  "request_id": "9cb7f50b8c7a4b6b",
  "errors": [
    {
      "name": "email",
      "reason": "value is not a valid email address",
      "pointer": "/body/email",
      "code": "value_error"
    }
  ]
}
```


## Authentication
- Keycloak (JWT)


## Authorization (RBAC)
- Keycloak — coarse roles.

Note: backend extension for fine-grained permissions is anticipated.


## Logging. General concept
The logging system is implemented as a unified structured event pipeline
with a single entry point for event emission and routing based on event type.

The system supports three categories of events:
- application
- audit
- security

All events use a common JSON-based envelope and pass through a shared pipeline
responsible for enrichment, validation, sanitization/redaction, and routing.

Each event type has its own policy rules, including:
- required fields
- sensitive data handling
- delivery mechanism
- storage requirements
- durability guarantees

The system is privacy-aware and follows data minimization and pseudonymization principles,
making it suitable for GDPR-compliant projects.

A single business operation may produce multiple structured events of different types
without duplicating routing logic or binding to a specific logging backend.

## Metrics and tracing
Metrics and tracing are optional and not included in the core.

## Security
The backend template provides a minimal security foundation.
Each project must review and adapt security requirements based on its context.

### Rate Limiting
Rate limiting should be implemented to protect public endpoints from abuse.

### CORS Configuration
CORS settings must be explicitly configured per environment.

### Responsibility
Security configuration is not fully defined by the template and must be
reviewed and extended per project requirements.

## Data & GDPR
The backend template is designed to be privacy-aware and follows
data minimization principles by default.

### Personal Data Handling
Sensitive and personal data must not be logged in raw form.

- Emails, identifiers and IP addresses must be masked, hashed, or replaced with internal references (e.g. actor_id)
- Secrets (passwords, tokens, API keys) must never be logged

The template includes Data Minimization and Right to Erasure features.
Data retention policies must be configurable per project.


## PostgreSQL, SQLAlchemy
For the primary key, UUID generated at the ORM level is used.

### ORM mixins:
- UUIDMixin
- TimestampMixin

### Models:
1. User model.
System user, identified via an external authentication provider.
Can exist without being linked to organization(s).
Fields: id (uuid), external_id (sub), email (cache, optional), created_at.

2. Organisation model.
Any user can create an organization.
The creator automatically becomes the owner.
If a user does not belong to any organization, they are an independent system user.
Fields: user_id, organisation_id, role: owner | admin | member
- created_at

3. Membership
- user_id
- organisation_id
- role: owner | member
- created_at

4. Invite
- Fields: id, organisation_id, email, role, token, expires_at, created_at

Rules:
A user may belong to no organisation.
A user may have only one active organisation membership at a time.
Multiple active organisations per user are not currently supported.
Membership is determined via Membership.
Historical membership rows can remain for transfer history, but only one is active.
The organisation creator automatically becomes owner (Membership role=owner).
Only Membership participants have access to the organisation.
Access to an organisation is provided through invitation or by owner/admin addition.

Business rules are defined and adjusted according to future tasks.

## Backup Strategy
Recovery objectives (RPO / RTO) are defined as project-level requirements.

Backup frequency, retention period, and restore test schedule must be configurable
and aligned with the target RPO / RTO.

Default storage provider: Cloudflare R2.

### PostgreSQL
- Default backup format: logical dump (`pg_dump`)
- Default backup frequency: daily
- Retention period: configurable
- Backups must not be stored only inside the running container
- Long-term storage must use external storage (e.g. Cloudflare R2)
- Local volume storage may be used only as temporary staging storage

### Keycloak (self-hosted)
- Database backup strategy must follow the same policy as PostgreSQL,
  unless project-specific requirements define otherwise

### Restore Validation
- Restore tests must be performed periodically
- Restore test frequency must be configurable
- Backups are not considered valid unless restore has been tested

### Deletion Reconciliation
- If the project requires irreversible deletion handling
  (e.g. GDPR-related user deletion),
  restore procedures must prevent deleted data from being reintroduced
  from historical backups
- Where applicable, a deletion log or equivalent reconciliation mechanism
  must be re-applied after restore

## Code Style
The project follows a consistent Python code style.

- snake_case for Python code
- plural resource names in API
- Linting is enforced with **Ruff**
- Formatting is enforced with **ruff format**
- Code should remain compatible with **PEP 8** where not overridden by the formatter
- Type hints are recommended for public interfaces and core business logic
- Style checks should be automated in development and CI


## Testing
The backend template defines a minimal testing strategy covering
different levels of the system.

### Unit Tests
Unit tests should cover core business logic and isolated components
(e.g. services, domain logic, utility functions).

External dependencies (database, APIs) must be mocked.

### Integration Tests
Integration tests should verify interaction between components,
including:

- API endpoints
- database integration
- authentication / authorization flows

These tests should use a test environment close to real system behavior.

### Contract Tests
Contract tests ensure that API responses remain consistent and
conform to the defined schema (e.g. OpenAPI or response models).

They protect against breaking changes in API structure.

### Principles
- Critical business logic must be covered by tests
- API behavior must be validated through integration tests
- Test coverage should focus on correctness, not only percentage


## Documentation
API documentation is generated automatically from OpenAPI schema
and exposed via Scalar UI.

Available at:
- `/openapi.json` — OpenAPI schema
- `/scalar` — Scalar UI
