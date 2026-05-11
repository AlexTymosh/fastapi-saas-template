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

Platform endpoint dependencies resolve platform actors in two layers:

```text
1. JWT is valid.
2. Local user projection exists.
3. user.status = active.
4. Active platform_staff record exists.
5. platform_staff.status = active.
6. The platform_staff role is mapped to backend permissions.
7. Endpoints that perform a business action check the required permission.
```

If any actor-resolution check fails, return 403 with a generic platform access denial, except missing/invalid JWT which should return 401. This keeps non-platform users, suspended users, missing staff rows, and suspended staff rows indistinguishable to callers.

`GET /api/v1/platform/me` uses the active-actor layer only. It intentionally does not require an arbitrary business permission such as `users:read` or `audit:read`, because its purpose is to describe the already authenticated platform actor.

## 6. Endpoint separation

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


## 7. Platform identity endpoint

`GET /api/v1/platform/me` is the safe platform/admin identity endpoint for the future admin frontend. After login, the frontend can call this endpoint to determine whether the current authenticated user has platform access, which platform role they have, which backend-derived permissions are available, and which administrative UI sections may be shown.

The endpoint returns safe identity and profile fields from the local backend projection and `platform_staff` row, including:

```text
user_id
staff_id
role
staff_status
permissions
email
email_verified
first_name
last_name
user_status
user_created_at
user_updated_at
staff_created_at
staff_updated_at
```

The `role` value is the local `platform_staff.role`. The `permissions` list is derived from the backend role-to-permission mapping for that local role. JWT-provided roles and permissions are not trusted and must not be used to grant platform access at request time.

Denied access behaviour is deliberately generic: missing local user projection, suspended local user, missing platform staff row, suspended platform staff row, invalid platform staff role, or insufficient platform access all return `403` through the common Problem Details error handlers. Missing or invalid authentication returns `401`. The endpoint must not create local users or platform staff rows.

The endpoint is protected by the `PLATFORM_READ_POLICY` rate-limit policy.

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
- Added `/api/v1/platform/*` endpoints for identity, users, organisations, and audit-events.
- Added `require_platform_permission()` DB-backed authorization; JWT roles must not grant request-time permissions.

- Platform access is DB-backed via `platform_staff`; JWT roles must never grant request-time backend permissions and may only become future controlled JIT provisioning input for local DB records.
- Platform actors can act only via `/api/v1/platform/*` and do not bypass tenant `/api/v1/organisations/*` endpoints.
- Platform write actions require a non-blank reason, are audited, and self-suspension is forbidden.
- Last-platform-admin hardening is deferred to future platform staff-management stage.
