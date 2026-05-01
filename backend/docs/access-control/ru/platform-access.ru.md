# Модель Platform Access

## 1. Назначение

Platform access используется для внутренней операционной работы:

- support;
- audit;
- compliance;
- emergency correction;
- user and organisation suspension;
- platform staff management.

Platform access не является тем же самым, что organisation membership.

## 2. Источник identity

Keycloak должен оставаться identity provider.

Keycloak отвечает за:

- registration;
- login;
- password reset;
- email verification;
- optional MFA;
- JWT issuance.

Backend отвечает за:

- local user projection;
- organisation membership;
- platform staff access;
- permissions;
- audit trail.

## 3. Backend как source of truth

Для полного контроля в backend platform authorization должна храниться в backend.

Рекомендуемая таблица:

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

Рекомендуемые роли:

```text
platform_admin
support_agent
compliance_officer
```

Рекомендуемые статусы:

```text
active
suspended
```

## 4. Permission mapping

Рекомендуемые permissions:

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

Рекомендуемый role mapping:

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

## 5. Разрешение Platform Actor

Platform endpoint dependency должна проверять:

```text
1. JWT is valid.
2. Local user projection exists.
3. user.status = active.
4. Active platform_staff record exists.
5. platform_staff.status = active.
6. role has required permission.
```

Если любая проверка не проходит, возвращать 403, кроме missing/invalid JWT — в этом случае 401.

## 6. Разделение endpoints

Platform actions должны использовать отдельные routes:

```text
/api/v1/platform/users/*
/api/v1/platform/organisations/*
/api/v1/platform/staff/*
/api/v1/platform/audit-events
```

Platform actors не должны bypass ordinary tenant endpoints.

## 7. Bootstrap первого Platform Admin

Первый platform admin должен создаваться management command, а не public API.

Пример команды:

```bash
python -m app.commands.create_platform_admin --email admin@example.com
```

Ожидаемое поведение:

```text
1. Find local user by email.
2. Create platform_staff with role=platform_admin.
3. Write bootstrap audit event.
```

Не разрешать public self-service creation of `platform_admin`.

## 8. Audit requirements

Все platform actions должны записывать audit events.

Рекомендуемая таблица:

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

Рекомендуемые audited actions:

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

## 9. Emergency Owner Correction

Tenant API не должен поддерживать ownership transfer.

Если появится реальный операционный кейс, добавить platform-only emergency endpoint:

```text
POST /api/v1/platform/organisations/{organisation_id}/owner-correction
```

Требования:

```text
- platform_admin only;
- mandatory reason;
- audit event required;
- no ordinary tenant endpoint;
- preferably two-person approval in future.
```
