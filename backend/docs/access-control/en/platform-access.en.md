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

The backend handles:

- local user projection;
- organisation membership;
- platform staff access;
- permissions;
- audit trail.

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

Recommended permissions:

```text
users:read
users:suspend
users:restore

organisations:read
organisations:suspend
organisations:restore

platform_staff:manage
audit:read

gdpr:export
gdpr:erase

data:correct
```

Recommended role mapping:

```text
platform_admin:
- users:read
- users:suspend
- users:restore
- organisations:read
- organisations:suspend
- organisations:restore
- platform_staff:manage
- audit:read
- gdpr:export
- gdpr:erase
- data:correct

support_agent:
- users:read limited
- organisations:read limited

compliance_officer:
- users:read limited
- organisations:read limited
- audit:read
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
6. role has required permission.
```

If any check fails, return 403, except missing/invalid JWT which should return 401.

## 6. Endpoint separation

Platform actions must use dedicated routes:

```text
/api/v1/platform/users/*
/api/v1/platform/organisations/*
/api/v1/platform/staff/*
/api/v1/platform/audit-events
```

Platform actors must not bypass ordinary tenant endpoints.

## 7. Bootstrap first platform admin

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

## 8. Audit requirements

All platform actions must write audit events.

Recommended table:

```text
platform_audit_events
- id
- actor_user_id
- action
- target_type
- target_id
- reason
- metadata_json
- created_at
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

## 9. Emergency owner correction

Tenant API must not support ownership transfer.

If a real operational case appears, add a platform-only emergency endpoint:

```text
POST /api/v1/platform/organisations/{organisation_id}/owner-correction
```

Requirements:

```text
- platform_admin only;
- mandatory reason;
- audit event required;
- no ordinary tenant endpoint;
- preferably two-person approval in future.
```
