# Platform Access Model

## 1. Purpose

Platform access is used for internal operational work:

- support;
- audit;
- compliance;
- emergency correction;
- user and organisation suspension;
- platform staff management;
- privacy and DSR operations.

Platform access is not the same as organisation membership.

## 2. Identity source

Keycloak should remain the identity provider.

Keycloak handles:

- registration;
- login;
- password reset;
- email verification;
- optional MFA;
- JWT issuance.

JWT claims are identity input only. Backend authorization must not trust external
JWT roles as request-time permissions.

The backend handles:

- local user projection;
- organisation membership;
- platform staff access;
- permissions;
- audit trail.

Authorization is DB-driven. `platform_admin`, `realm_access.roles`,
`resource_access.*.roles`, direct `roles`, legacy `superadmin`, and similar IdP
role claims must never grant backend tenant/platform permissions directly at
request time.

## 3. Backend source of truth

Platform authorization is stored in the backend `platform_staff` table.

Current roles:

```text
platform_admin
support_agent
compliance_officer
```

Current statuses:

```text
active
suspended
```

## 4. Permission mapping

Recommended permissions:

```text
users:read
users:read_limited
users:suspend
users:restore
users:correct_profile

organisations:read
organisations:read_limited
organisations:suspend
organisations:restore
organisations:correct_profile
organisations:emergency_owner_correction

platform_staff:manage
audit:read
audit:read_limited

gdpr:export
gdpr:erase
privacy_requests:read
privacy_requests:review
privacy_requests:execute_erasure
privacy_export_artifacts:read
```

Current role mapping:

```text
platform_admin:
- all permissions

support_agent:
- users:read_limited
- organisations:read_limited
- audit:read_limited (only if required for support cases)

compliance_officer:
- users:read_limited
- organisations:read_limited
- audit:read
- audit:read_limited
- gdpr:export
- gdpr:erase
- privacy_requests:read
- privacy_requests:review
- privacy_requests:execute_erasure
- privacy_export_artifacts:read
```

## 5. Platform actor resolution

Platform endpoint dependency should check:

```text
1. JWT is valid.
2. Local user projection exists.
3. user.status = active.
4. Active platform_staff record exists.
5. platform_staff.status = active.
6. role has required permission, unless the endpoint only needs the active
   platform identity.
```

If any check fails, return `403`, except missing/invalid JWT which should return
`401`.

## 6. Platform identity endpoint

`GET /api/v1/platform/me` exposes the safe platform identity for the currently
authenticated actor.

The role and permissions in the response are resolved only from the local
`platform_staff` row and backend role-to-permission mapping. JWT roles,
`realm_access`, `resource_access`, direct `roles`, and similar IdP claims are not
trusted for platform authorization.

## 7. Endpoint separation

Platform actors must use dedicated routes:

```text
/api/v1/platform/me
/api/v1/platform/users/*
/api/v1/platform/organisations/*
/api/v1/platform/staff/*
/api/v1/platform/audit-events
/api/v1/platform/audit-events/limited
/api/v1/platform/privacy/data-subject-requests*
/api/v1/platform/privacy/export-artifacts*
```

Platform actors must not bypass ordinary tenant endpoints.

A `platform_admin` who is not a member of organisation X must receive `403` from:

```text
GET /api/v1/organisations/{organisation_id}
```

The same actor may use a dedicated platform endpoint:

```text
GET /api/v1/platform/organisations/{organisation_id}
```

## 8. Full and limited platform views

Full platform list and detail views are reserved for `platform_admin` or actors
with the corresponding full permissions from `ROLE_PERMISSIONS`.

Limited platform views are separate endpoints for `support_agent` and
`compliance_officer` according to `ROLE_PERMISSIONS`. They intentionally expose
reduced DTOs and must not be treated as aliases for full platform views.

Current limited view endpoints:

```text
GET /api/v1/platform/users/limited
GET /api/v1/platform/organisations/limited
GET /api/v1/platform/audit-events/limited
```

Limited views must not expose restricted operational fields, raw audit metadata,
raw actor ids, network identifiers, credential data, or token material.

## 9. Privacy and DSR platform access

DSR platform endpoints are grouped under:

```text
/api/v1/platform/privacy/*
```

Required permission boundaries:

| Area | Permission |
|---|---|
| DSR list/detail reads | `privacy_requests:read` |
| DSR review/approve/reject/cancel | `privacy_requests:review` |
| Approved erase execution | `privacy_requests:execute_erasure` |
| Export artifact metadata list/detail | `privacy_export_artifacts:read` |
| Export artifact creation | `gdpr:export` |
| Export artifact download URL creation | `gdpr:export` |

`support_agent` has no DSR/export-artifact access by default.

`compliance_officer` can read/review DSRs, execute approved erasure through the
dedicated boundary, read export artifact metadata, and create export artifacts.

## 10. Future admin frontend and OpenAPI contract

`GET /api/v1/platform/me` is the first endpoint a future admin frontend should
call after login.

Generated frontend clients should rely on stable platform paths, tags, response
models, and operation IDs.

Platform OpenAPI tags are grouped by platform area:

```text
platform-identity
platform-users
platform-organisations
platform-staff
platform-audit
platform-privacy
```

Backend contract tests must freeze exact operation IDs for platform routes and
must fail if a platform route is accidentally undocumented, untagged, missing a
response model, or missing its expected rate-limit policy.

## 11. Permission matrix testing

Backend tests must prove broken function-level authorization protection across
platform endpoints for:

```text
unauthenticated users
authenticated non-platform users
suspended local users
suspended platform staff
support_agent
compliance_officer
platform_admin
```

The matrix must also prove that:

- limited DTOs do not expose forbidden fields;
- denied platform writes do not create audit events;
- platform permissions are resolved from local `platform_staff` records rather
  than JWT roles;
- DSR/export-artifact endpoints use the `platform-privacy` tag;
- privacy permissions are enforced separately from generic platform read/write
  permissions.

## 12. Platform-created organisations and initial owner assignment

When a standalone tenant user creates an organisation, that creator becomes
`owner`.

When a platform actor creates an organisation through a platform endpoint:

- the platform actor must not become tenant owner automatically;
- platform roles must not create tenant membership implicitly;
- the endpoint must require explicit initial owner assignment via
  `initial_owner_user_id` or `initial_owner_email`.

Ownerless organisation creation is a special bootstrap/operational case and must
not be the default path.

## 13. Bootstrap first platform admin

The first platform admin should be created by a management command, not by
public API.

Example command from `backend/`:

```bash
uv run python -m app.commands.make_platform_admin --email admin@example.com
```

Do not allow public self-service creation of `platform_admin`. Do not bootstrap
platform access with Keycloak roles or manual database edits.

## 14. Audit requirements

All platform actions must write audit events.

Shared audit table for tenant + platform sensitive actions:

```text
audit_events
- id
- actor_user_id
- category
- action
- target_type
- target_id
- reason
- metadata_json
- created_at
```

Recommended categories:

```text
tenant
platform
security
compliance
```

Privacy/DSR execution audit events must avoid storing raw export payloads,
signed URLs, storage keys, local paths, processing tokens, or unsafe free-text
details.

## 15. OpenAPI contract for generated admin clients

Contract rules:

- Route handler names are the generated-client method names and must remain
  globally unique across all schema-included routes.
- Route handler names should be stable, descriptive, snake_case, and
  TypeScript-friendly.
- Platform routes must use only these tags:
  - `platform-identity`
  - `platform-users`
  - `platform-organisations`
  - `platform-staff`
  - `platform-audit`
  - `platform-privacy`
- Platform routes must not use the generic `platform` tag.
- Health routes must not use platform tags.
- Platform routes that return a body must declare a strict Pydantic
  `response_model`.
- Platform collection responses should use the standard envelope:
  `{ "data": [], "meta": {}, "links": {} }`.
- Limited platform views must not expose restricted operational fields.
- Platform read and write routes must carry explicit route-level rate-limit
  dependency metadata.

Future admin clients may rely on `operationId` values as stable method names,
but any route rename is an API-contract change and must be reviewed with the
same care as a path or schema change.
