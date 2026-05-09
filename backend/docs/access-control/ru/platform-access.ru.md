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

JWT claims являются только identity input. Backend authorization не должен доверять внешним JWT roles как request-time permissions.

Backend отвечает за:

- local user projection;
- organisation membership;
- platform staff access;
- permissions;
- audit trail.

Authorization является DB-driven. `platform_admin`, `realm_access.roles`, `resource_access.*.roles`, прямые `roles`, legacy `superadmin` и похожие IdP role claims не должны напрямую выдавать backend tenant/platform permissions во время обработки запроса. В будущем внешние IdP roles могут рассматриваться только как вход для controlled, idempotent, audited JIT provisioning, который записывает локальные `memberships` или `platform_staff` records до выдачи permissions.

## 3. Backend как source of truth

Platform authorization хранится в backend-таблице `platform_staff`.

Текущая таблица:

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

Текущие роли:

```text
platform_admin
support_agent
compliance_officer
```

Текущие статусы:

```text
active
suspended
```

## 4. Permission mapping

Текущие permissions:

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

Текущий role mapping:

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
- audit:read_limited

compliance_officer:
- users:read_limited
- organisations:read_limited
- audit:read
- audit:read_limited
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
/api/v1/platform/audit-events/limited
```

Platform actors не должны bypass ordinary tenant endpoints.

Limited audit view (`/api/v1/platform/audit-events/limited`) предназначен для `AUDIT_READ_LIMITED` и не должен отдавать raw `metadata_json`, `ip_address`, `user_agent`, free-text `reason` или прямой `actor_user_id`.

## 7. Bootstrap первого Platform Admin

Первый platform admin должен создаваться management command, а не public API.

Пример команды:

```bash
python -m app.commands.make_platform_admin --email admin@example.com
```

Ожидаемое поведение:

```text
1. Find an existing local user by email.
2. Require that user to be active.
3. Create active `platform_staff` with `role=platform_admin`, or exit successfully if it already exists.
4. Write bootstrap audit event when a new grant is made.
```

Не разрешать public self-service creation of `platform_admin`. Не использовать Keycloak roles для bootstrap platform-доступа и избегать ручных правок базы данных.

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
