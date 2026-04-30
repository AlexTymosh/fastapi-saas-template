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

JWT claims are identity input only. Backend authorization must not trust external JWT roles.

The backend handles:

- local user projection;
- organisation membership;
- platform staff access;
- permissions;
- audit trail.

`superadmin`, `platform_admin`, `realm_access.roles`, `resource_access.*.roles`, and similar JWT role claims must not grant backend tenant/platform permissions by themselves.

## 3. Backend source of truth

For full backend control, platform authorization should be stored in the backend.

Recommended table:

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

Recommended roles:

```text
platform_admin
support_agent
compliance_officer
```

Recommended statuses:

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

Recommended role mapping:

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
- gdpr:erase (only with approval or explicit future workflow)
```

## 5. Platform actor resolution

Platform endpoint dependency should check:

```text
1. JWT is valid.
2. Local user projection exists.
3. user.status = active.
4. Active platform_staff record exists.
5. platform_staff.status = active.
6. role has required permission.
```

If any check fails, return 403, except missing/invalid JWT which should return 401.

## 6. Endpoint separation

Platform actors must use dedicated routes:

```text
/api/v1/platform/users/*
/api/v1/platform/organisations/*
/api/v1/platform/staff/*
/api/v1/platform/audit-events
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

## 7. Platform-created organisations and initial owner assignment

When a standalone tenant user creates an organisation, that creator becomes `owner`.

When a platform actor creates an organisation through a platform endpoint:

- the platform actor must not become tenant owner automatically;
- platform roles must not create tenant membership implicitly;
- the endpoint must require explicit initial owner assignment via `initial_owner_user_id` or `initial_owner_email`.

Ownerless organisation creation is a special bootstrap/operational case and must not be the default path.

## 8. Bootstrap first platform admin

The first platform admin should be created by a management command, not by public API.

Example command:

```bash
python -m app.commands.create_platform_admin --email admin@example.com
```

Expected behaviour:

```text
1. Find local user by email.
2. Create platform_staff with role=platform_admin.
3. Write bootstrap audit event.
```

Do not allow public self-service creation of `platform_admin`.

## 9. Audit requirements

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

## 10. Emergency owner correction

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
