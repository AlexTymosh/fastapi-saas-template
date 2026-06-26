# Admin Frontend Client Generation

## Purpose

This document defines how a future admin frontend should generate and refresh
its TypeScript API client from the backend OpenAPI schema.

The backend is the source of truth for:

- API paths;
- request and response schemas;
- OpenAPI tags;
- `operationId` values;
- authentication and authorization boundaries;
- platform/admin contract tests.

This document does not implement a frontend application. It only defines the
expected workflow for generating a frontend client when the admin UI is
introduced.

## Current status

The project is currently a backend-only FastAPI SaaS template. The admin
frontend is planned but not implemented yet.

The backend already exposes platform/admin endpoints under:

```text
/api/v1/platform/*
```

The future admin frontend should use:

```text
GET /api/v1/platform/me
```

as the first request after login to resolve the current platform actor, role,
status, and effective permissions.

## OpenAPI contract rules

The backend OpenAPI schema is intended to be safe for generated frontend clients.

The current contract rules are:

- OpenAPI `operationId` values are generated from FastAPI `APIRoute.name`.
- Route handler names are generated-client method names.
- Route handler names must be globally unique across schema-included routes.
- Route handler names must be stable, descriptive, snake_case, and
  frontend-friendly.
- Renaming a route handler is an API contract change.
- Platform routes must use specific tags:
  - `platform-identity`
  - `platform-users`
  - `platform-organisations`
  - `platform-staff`
  - `platform-audit`
  - `platform-privacy`
- Platform routes must not use the generic `platform` tag.
- Platform routes that return a body must declare a strict Pydantic
  `response_model`.
- Platform collection responses must use the standard envelope:

```json
{
  "data": [],
  "meta": {},
  "links": {}
}
```

- Limited platform views must not expose restricted operational fields.
- Platform routes must keep their expected rate-limit policy metadata.

## Backend validation before generating a client

Before generating or refreshing a frontend client, run the backend contract
tests from `backend/`:

```bash
uv run pytest -q tests/contracts/test_openapi_platform_contract.py
```

Recommended broader checks from `backend/`:

```bash
uv run pytest -q -m "not external_db"
uv run pytest -q -m "security and not external_db"
uv run ruff check .
uv run ruff format --check .
```

If these checks fail, do not regenerate and commit a new frontend client. Fix the
backend contract first.

## Exporting the OpenAPI schema

Start the backend locally with documentation enabled.

Example from `backend/`:

```bash
uv run uvicorn app.main:app --reload
```

Then export the OpenAPI schema:

```bash
curl http://localhost:8000/openapi.json -o openapi.json
```

If the backend runs on a different port, update the URL accordingly.

The exported schema should be treated as a generated artifact. Do not manually
edit it.

## Recommended future frontend location

When the frontend application is added, prefer a clear generated-client boundary
such as:

```text
frontend/src/api/generated/
```

or for an admin-only frontend:

```text
frontend/src/admin/api/generated/
```

The generated directory should contain only generated files.

Hand-written API wrappers, hooks, query clients, or UI adapters should live
outside the generated directory, for example:

```text
frontend/src/admin/api/client.ts
frontend/src/admin/api/hooks/
frontend/src/admin/features/
```

## Recommended generation strategy

The exact generator should be chosen when the frontend stack is created.

Recommended TypeScript-friendly options:

1. Type-only generation:
   - generate TypeScript types from OpenAPI;
   - use a small hand-written fetch wrapper;
   - good when the team wants explicit control over requests.
2. Client generation:
   - generate typed request functions from OpenAPI;
   - good when the team wants faster CRUD screen development.

The important rule is not the specific generator. The important rule is that
generated method names must come from backend `operationId` values.

## Example type-only workflow

Example command shape:

```bash
npx openapi-typescript ./openapi.json   -o ./frontend/src/admin/api/generated/schema.ts
```

Then keep a small hand-written client wrapper outside the generated folder:

```text
frontend/src/admin/api/client.ts
```

The wrapper should handle:

- base API URL;
- bearer token attachment;
- `X-Request-ID` if needed;
- Problem Details error parsing;
- 401/403 handling;
- `Retry-After` handling for 429 responses.

## Example generated-client workflow

Example command shape:

```bash
npx @hey-api/openapi-ts -i ./openapi.json   -o ./frontend/src/admin/api/generated
```

Generator configuration should preserve backend `operationId` values as frontend
method names where possible.

If a generator transforms `snake_case` into `camelCase`, the transformation
should be deterministic and documented.

## Authentication assumptions

The admin frontend should authenticate users through Keycloak/OIDC.

The frontend must send backend API requests with a valid access token:

```http
Authorization: Bearer <access-token>
```

The backend must not trust frontend-provided roles or permissions.

The frontend should not infer platform access from Keycloak roles. It must call:

```text
GET /api/v1/platform/me
```

and use the backend response as the source of truth for:

- platform access availability;
- platform role;
- platform staff status;
- effective permissions;
- visible admin UI sections.

## CORS assumptions

When a browser-based admin frontend is introduced, configure CORS explicitly.

Do not use wildcard origins in production.

Expected environment shape:

```text
CORS__ENABLED=true
CORS__ALLOW_ORIGINS=["http://localhost:3000","http://localhost:5173"]
CORS__ALLOW_CREDENTIALS=false
CORS__ALLOW_HEADERS=["Authorization","Content-Type","X-Request-ID"]
CORS__EXPOSE_HEADERS=["X-Request-ID","Retry-After"]
```

Production origins must be explicit HTTPS origins.

## Handling backend contract changes

A backend change should be treated as a frontend client contract change if it
modifies any of the following:

- route path;
- HTTP method;
- request schema;
- response schema;
- response status code;
- OpenAPI tag;
- `operationId`;
- authentication requirement;
- authorization requirement;
- rate-limit response behaviour.

When such a change is intentional:

1. Update backend tests.
2. Update backend documentation.
3. Export a fresh OpenAPI schema.
4. Regenerate the frontend client.
5. Update hand-written frontend wrappers or hooks.
6. Run frontend type checks and tests.

## Generated code policy

Generated client files should not be edited manually.

Recommended generated file header:

```text
// This file is generated from the backend OpenAPI schema.
// Do not edit manually.
// Regenerate using the documented OpenAPI client generation workflow.
```

Generated files may be committed if the frontend project uses committed generated
clients. If the project later chooses generation during CI/build, document that
decision explicitly.

## Review checklist

Before accepting a regenerated frontend client, verify:

- backend contract tests passed;
- generated method names are stable and readable;
- no unexpected `any` types appeared in platform/admin responses;
- limited platform DTOs still omit restricted fields;
- Problem Details errors are handled by frontend wrappers;
- 401, 403, and 429 flows are handled;
- `Retry-After` remains available to browser clients;
- no generated file was manually edited;
- no frontend code depends on Keycloak roles for backend authorization.

## Known non-goals

This document does not define:

- frontend framework choice;
- UI component library;
- frontend routing;
- state management;
- deployment topology;
- complete admin UX;
- public tenant frontend client generation.

Those decisions should be made in the future frontend implementation stage.
