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

## 8. Platform-created organisations and initial owner assignment

When a standalone tenant user creates an organisation, that creator becomes `owner`.

When a platform actor creates an organisation through a platform endpoint:

- the platform actor must not become tenant owner automatically;
- platform roles must not create tenant membership implicitly;
- the endpoint must require explicit initial owner assignment via `initial_owner_user_id` or `initial_owner_email`.

Ownerless organisation creation is a special bootstrap/operational case and must not be the default path.

## 9. Bootstrap first platform admin

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

## 10. Audit requirements

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

## 11. Emergency owner correction

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
- Added `/api/v1/platform/*` endpoints for users, organisations, and audit-events.
- Added `require_platform_permission()` DB-backed authorization; JWT roles must not grant request-time permissions.

- Platform access is DB-backed via `platform_staff`; JWT roles must never grant request-time backend permissions and may only become future controlled JIT provisioning input for local DB records.
- Platform actors can act only via `/api/v1/platform/*` and do not bypass tenant `/api/v1/organisations/*` endpoints.
- Platform write actions require a non-blank reason, are audited, and self-suspension is forbidden.
- Last-platform-admin hardening is deferred to future platform staff-management stage.

## 11. Limited platform views

Limited platform views provide safe read-only records for future admin frontend roles that should not receive full operational DTOs.

Current limited endpoints:

```text
GET /api/v1/platform/users/limited
GET /api/v1/platform/organisations/limited
GET /api/v1/platform/audit-events/limited
```

Access requirements:

- `GET /api/v1/platform/users/limited` requires `users:read_limited`.
- `GET /api/v1/platform/organisations/limited` requires `organisations:read_limited`.
- `GET /api/v1/platform/audit-events/limited` requires `audit:read_limited`.
- All limited views are read-only and must be covered by the appropriate platform read or audit read rate-limit policy.

Limited user records intentionally expose only `id`, `first_name`, `last_name`, `status`, and `created_at`. They do not expose full email, `external_auth_id`, `email_verified`, onboarding state, suspension reason, suspension timestamp, audit metadata, or credential/token data. Backend search may use email internally, but the limited response must not return the full email address.

Limited organisation records intentionally expose only `id`, `name`, `slug`, `status`, and `created_at`. They do not expose `suspended_reason`, `deleted_at`, owner internals, membership internals, or audit metadata. Deleted organisations are excluded from the limited organisation endpoint by default.

The full platform user and organisation endpoints remain restricted to `users:read` and `organisations:read` respectively. `platform_admin` can access both full and limited views. `support_agent` can access limited user, organisation, and audit views only. `compliance_officer` can access limited user and organisation views and audit views according to the backend role-to-permission mapping.

## 12. Admin frontend contract tests

The platform backend contract is locked down with OpenAPI and authorization tests before any admin frontend is generated from the schema.

Contract expectations:

- OpenAPI operation IDs are unique.
- Platform routes use stable operation IDs.
- Platform routes use clear platform tags such as `platform-identity`, `platform-users`, `platform-organisations`, `platform-staff`, and `platform-audit`.
- Platform routes have documented success response schemas.
- Platform read and write routes declare the expected rate-limit policy metadata.
- Health endpoints are not tagged as platform endpoints.

Security expectations:

- Unauthenticated requests receive `401`.
- Authenticated non-platform users, missing local user projections, suspended local users, and suspended platform staff receive generic platform access denial.
- Limited platform roles cannot access full platform views or write endpoints.
- Denied platform writes must not create audit events.
- Field-level authorization tests verify that limited DTOs keep sensitive fields out of API responses.
