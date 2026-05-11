# Platform Access Model

## 1. Purpose

Platform access is used for internal operational work:

- support;
- audit;
- compliance;
- emergency correction;
- user and organisation suspension;
- platform staff management.

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

JWT claims are identity input only. Backend authorization must not trust external JWT roles as request-time permissions.

The backend handles:

- local user projection;
- organisation membership;
- platform staff access;
- permissions;
- audit trail.

Authorization is DB-driven. `platform_admin`, `realm_access.roles`, `resource_access.*.roles`, direct `roles`, legacy `superadmin`, and similar IdP role claims must never grant backend tenant/platform permissions directly at request time. External IdP roles may only be considered in the future as input for controlled, idempotent, audited JIT provisioning that writes local `memberships` or `platform_staff` records before permissions are granted.

## 3. Backend source of truth

Platform authorization is stored in the backend `platform_staff` table.

Current table:

```text
platform_staff
- id
- user_id
- role
- status
- created_by_user_id
- created_at
- updated_at
```

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

Recommended permissions (strict enum-like names):

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
```

Current role mapping:

```text
platform_admin:
- users:read
- users:read_limited
- users:suspend
- users:restore
- users:correct_profile
- organisations:read
- organisations:read_limited
- organisations:suspend
- organisations:restore
- organisations:correct_profile
- organisations:emergency_owner_correction
- platform_staff:manage
- audit:read
- audit:read_limited
- gdpr:export
- gdpr:erase

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
```

## 5. Platform actor resolution

Platform endpoint dependency should check:

```text
1. JWT is valid.
2. Local user projection exists.
3. user.status = active.
4. Active platform_staff record exists.
5. platform_staff.status = active.
6. role has required permission, unless the endpoint only needs the active platform identity.
```

If any check fails, return 403, except missing/invalid JWT which should return 401.

## 6. Platform identity endpoint

`GET /api/v1/platform/me` exposes the safe platform identity for the currently authenticated actor. It is intended for a future admin frontend immediately after login so the frontend can decide whether platform access is available and which admin UI sections should be shown.

The endpoint returns the local `user_id`, `staff_id`, platform `role`, `staff_status`, effective platform `permissions`, safe profile fields (`email`, `email_verified`, `first_name`, `last_name`), `user_status`, and relevant user/staff timestamps. It must not expose internal ORM objects, `external_auth_id`, suspension reasons, raw audit metadata, or credential/token data.

The role and permissions in the response are resolved only from the local `platform_staff` row and backend role-to-permission mapping. JWT roles, `realm_access`, `resource_access`, direct `roles`, and similar IdP claims are not trusted for platform authorization.

`GET /api/v1/platform/me` requires an authenticated principal, an existing local user projection, `user.status = active`, an existing `platform_staff` row, and `platform_staff.status = active`. It resolves an active platform actor without requiring an arbitrary business permission such as `users:read` or `audit:read`. Non-platform users, suspended local users, missing staff rows, and suspended staff rows receive the same generic `403` platform access denial. Missing or invalid authentication receives `401`.

The endpoint is read-only and must be protected by the platform read rate-limit policy. It does not create users, does not create staff records, and does not grant access from JWT-provided roles.

## 7. Endpoint separation

Platform actors must use dedicated routes:

```text
/api/v1/platform/me
/api/v1/platform/users/*
/api/v1/platform/organisations/*
/api/v1/platform/staff/*
/api/v1/platform/audit-events
/api/v1/platform/audit-events/limited
```

Platform actors must not bypass ordinary tenant endpoints.

Limited audit view (`/api/v1/platform/audit-events/limited`) is for `AUDIT_READ_LIMITED` and must not expose raw `metadata_json`, `ip_address`, `user_agent`, free-text `reason`, or direct `actor_user_id`.

A `platform_admin` who is not a member of organisation X must receive `403` from:

```text
GET /api/v1/organisations/{organisation_id}
```

The same actor may use a dedicated platform endpoint:

```text
GET /api/v1/platform/organisations/{organisation_id}
```


## 8. Full and limited platform views

Full platform list and detail views are reserved for `platform_admin` or actors with the corresponding full permissions from `ROLE_PERMISSIONS`, such as `users:read`, `organisations:read`, `platform_staff:manage`, or `audit:read`. Full views may expose operational fields required for privileged support, audit, compliance, or recovery workflows.

Limited platform views are separate endpoints for `support_agent` and `compliance_officer` according to `ROLE_PERMISSIONS`. They intentionally expose reduced DTOs and must not be treated as aliases for full platform views. Current limited view endpoints are:

```text
GET /api/v1/platform/users/limited
GET /api/v1/platform/organisations/limited
GET /api/v1/platform/audit-events/limited
```

The limited user DTO may contain only:

```text
id
first_name
last_name
status
created_at
```

The limited user DTO must not return `email`, `external_auth_id`, `email_verified`, `suspended_at`, `suspended_reason`, onboarding or other internal fields, token or credential data, or audit metadata. Its `q` parameter searches only `first_name` and `last_name` so hidden email addresses cannot be inferred through partial search. The optional `exact_email` parameter exists for support discovery workflows, uses exact email-match semantics after normalisation, and still must not expose email in the limited response.

The limited organisation DTO may contain only:

```text
id
name
slug
status
created_at
```

The limited organisation DTO must not return `suspended_at`, `suspended_reason`, `deleted_at`, owner internals, membership internals, or audit metadata. Deleted organisations are excluded from limited views by default. Full platform organisation endpoints may have broader operational visibility, including intentional visibility of soft-deleted organisations where required for support, audit, compliance, or recovery workflows.

Limited list endpoints support these query parameters unless a route-specific contract says otherwise. `limit` is capped at `100`, and `offset` must be non-negative:

```text
limit
offset
status
q
```

`GET /api/v1/platform/users/limited` also supports:

```text
exact_email
```

Ordering must be deterministic for both full and limited platform lists:

```text
created_at desc
id desc
```

## 9. Future admin frontend and OpenAPI contract

`GET /api/v1/platform/me` is the first endpoint a future admin frontend should call after login. The frontend should use it to determine whether platform access is available and which sections may be shown for the resolved local platform role and permissions.

Generated frontend clients should rely on stable platform paths, tags, response models, and operation IDs. Platform OpenAPI tags are grouped by platform area:

```text
platform-identity
platform-users
platform-organisations
platform-staff
platform-audit
```

Backend contract tests must freeze exact operation IDs for platform routes and must fail if a platform route is accidentally undocumented, untagged, missing a response model, or missing its expected rate-limit policy.

## 10. Permission matrix testing

Backend tests must prove broken function-level authorization protection across platform endpoints for:

```text
unauthenticated users
authenticated non-platform users
suspended local users
suspended platform staff
support_agent
compliance_officer
platform_admin
```

The matrix must also prove that limited DTOs do not expose forbidden fields, denied platform writes do not create audit events, and platform permissions are resolved from local `platform_staff` records rather than JWT roles.

## 11. Platform-created organisations and initial owner assignment

When a standalone tenant user creates an organisation, that creator becomes `owner`.

When a platform actor creates an organisation through a platform endpoint:

- the platform actor must not become tenant owner automatically;
- platform roles must not create tenant membership implicitly;
- the endpoint must require explicit initial owner assignment via `initial_owner_user_id` or `initial_owner_email`.

Ownerless organisation creation is a special bootstrap/operational case and must not be the default path.

## 12. Bootstrap first platform admin

The first platform admin should be created by a management command, not by public API.

Example command:

```bash
python -m app.commands.make_platform_admin --email admin@example.com
```

Expected behaviour:

```text
1. Find an existing local user by email.
2. Require that user to be active.
3. Create an active `platform_staff` row with `role=platform_admin`, or exit successfully if it already exists.
4. Write a bootstrap audit event when a new grant is made.
```

Do not allow public self-service creation of `platform_admin`. Do not bootstrap platform access with Keycloak roles or manual database edits.

## 13. Audit requirements

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

Recommended audited actions:

```text
user_suspended
user_restored
organisation_suspended
organisation_restored
platform_staff_created
platform_staff_removed
platform_staff_suspended
data_corrected
gdpr_export_requested
gdpr_erasure_requested
```

## 14. Emergency owner correction

Tenant API must not support ownership transfer.

If a real operational case appears, add a platform-only emergency endpoint:

```text
POST /api/v1/platform/organisations/{organisation_id}/owner-correction
```

Requirements:

```text
- organisations:emergency_owner_correction permission;
- mandatory reason;
- audit event required;
- no ordinary tenant endpoint;
- preferably two-person approval in future.
```

Current implementation note: an internal-only service flow is available via
`PlatformOrganisationsService.emergency_replace_organisation_owner`. It performs
an atomic owner replacement and writes a platform audit event. This remains an
internal operational path until a dedicated public API contract is introduced.


## Implementation status update (2026-04-30)
- Added backend-managed `platform_staff` foundation.
- Added `/api/v1/platform/*` endpoints for identity, users, organisations, staff, and audit-events.
- Added `require_platform_permission()` DB-backed authorization; JWT roles must not grant request-time permissions.

- Platform access is DB-backed via `platform_staff`; JWT roles must never grant request-time backend permissions and may only become future controlled JIT provisioning input for local DB records.
- Platform actors can act only via `/api/v1/platform/*` and do not bypass tenant `/api/v1/organisations/*` endpoints.
- Platform write actions require a non-blank reason, are audited, and self-suspension is forbidden.
- Last-platform-admin hardening is implemented for platform staff demotion and suspension flows.
