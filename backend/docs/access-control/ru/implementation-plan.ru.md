# План реализации Access Control

## Цель

Удалить концепцию `superadmin` из tenant/business logic и ввести чистое разделение между:

```text
Tenant access:
- owner
- admin
- member

Platform access:
- platform_admin
- support_agent
- compliance_officer
```

## PR 1 — Remove `superadmin` bypass from tenant flows

Suggested commit:

```text
🔐 fix(authz): remove superadmin bypass from tenant flows
```

### Файлы для изменения

```text
backend/app/core/auth_claims.py
backend/app/organisations/api/organisations.py
backend/app/organisations/services/access.py
```

### Задачи

- Remove `is_superadmin()`.
- Remove special branch from `POST /api/v1/organisations`.
- Remove platform bypass from organisation access service.
- Keep self-service organisation creation through onboarding service.
- Add regression tests.

### Tests

```text
- self-service user can create organisation and becomes owner
- user with active membership cannot create second organisation
- platform-like role does not grant ordinary tenant access
```

---

## PR 2 — Add user and organisation statuses

Suggested commit:

```text
🚦 feat(domain): add suspendable users and organisations
```

### Добавить

```text
users.status
users.suspended_at
users.suspended_reason

organisations.status
organisations.suspended_at
organisations.suspended_reason
```

### Rules

```text
- suspended user cannot perform tenant actions
- suspended user cannot accept invite
- suspended user cannot create organisation
- suspended organisation blocks ordinary tenant actions
```

### Tests

```text
- suspended user gets 403 on tenant action
- suspended organisation blocks member/admin/owner actions
```

---

## PR 3 — Add organisation update endpoint

Suggested commit:

```text
🏢 feat(organisations): allow owner and admin to update name and slug
```

### Recommended endpoint

```text
PATCH /api/v1/organisations/{organisation_id}
```

### Payload

```json
{
  "name": "New Organisation Name",
  "slug": "new-organisation-slug"
}
```

### Rules

```text
- owner can update name and slug
- admin can update name and slug
- member cannot update name or slug
- suspended organisation cannot be updated through tenant API
```

### Migration impact

Database migration не требуется, если constraints для name/slug не меняются.

---

## PR 4 — Add membership management

Suggested commit:

```text
👥 feat(memberships): add role management and member removal
```

### Endpoints

```text
PATCH  /api/v1/organisations/{organisation_id}/memberships/{membership_id}/role
DELETE /api/v1/organisations/{organisation_id}/memberships/{membership_id}
```

### Role update rules

```text
owner:
- member -> admin
- admin -> member
- owner -> anything: forbidden

admin:
- cannot change roles

member:
- cannot change roles
```

### Delete rules

```text
owner:
- can delete admin
- can delete member
- cannot delete owner

admin:
- can delete member
- cannot delete admin
- cannot delete owner

member:
- cannot delete anyone
```

### Tests

```text
- owner can promote member to admin
- owner can demote admin to member
- owner cannot demote owner
- admin cannot change roles
- owner can remove admin/member
- admin can remove member only
- owner cannot be removed
```

---

## PR 5 — Harden invite lifecycle

Suggested commit:

```text
✉️ feat(invites): harden invite lifecycle and revocation rules
```

### Добавить

```text
DELETE /api/v1/organisations/{organisation_id}/invites/{invite_id}
POST   /api/v1/organisations/{organisation_id}/invites/{invite_id}/resend
```

### Rules

```text
- owner can invite member/admin
- admin can invite member only
- nobody can invite owner
- accept invite requires email_verified=true
- accept invite requires active user
- accept invite requires active organisation
- duplicate pending invite for same email+organisation is forbidden
- revoked invite cannot be accepted
```

### Tests

```text
- owner can invite admin
- admin cannot invite admin
- admin can invite member
- member cannot invite
- duplicate pending invite returns 409
- unverified email cannot accept invite
```

---

## PR 6 — Add platform staff foundation

Suggested commit:

```text
🛡️ feat(platform): add platform staff roles and permissions
```

### Add module

```text
backend/app/platform/
  api/
  models/
  repositories/
  schemas/
  services/
```

### Add core permission dependency

```text
backend/app/core/platform/
  actors.py
  permissions.py
  dependencies.py
```

### Add model

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

### Add dependency

```text
require_platform_permission(permission)
```

### Tests

```text
- regular user cannot access platform endpoint
- owner cannot access platform endpoint
- platform_admin can access platform endpoint
- suspended platform staff cannot access platform endpoint
```

---

## PR 7 — Add platform administration endpoints

Suggested commit:

```text
🛠️ feat(platform): add audited platform administration endpoints
```

### Endpoints

```text
POST /api/v1/platform/users/{user_id}/suspend
POST /api/v1/platform/users/{user_id}/restore

POST /api/v1/platform/organisations/{organisation_id}/suspend
POST /api/v1/platform/organisations/{organisation_id}/restore

PATCH /api/v1/platform/organisations/{organisation_id}
GET   /api/v1/platform/audit-events
```

### Tests

```text
- platform_admin can suspend user
- platform_admin can restore user
- support_agent cannot suspend user
- platform_admin can suspend organisation
- suspended organisation blocks tenant actions
```

---

## PR 8 — Add audit trail

Suggested commit:

```text
🧾 feat(audit): record sensitive tenant and platform actions
```

### Add table

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

### Audit actions

```text
organisation_name_changed
organisation_slug_changed
organisation_deleted
member_removed
membership_role_changed
invite_created
invite_revoked
invite_resent
user_suspended
user_restored
organisation_suspended
organisation_restored
platform_staff_created
platform_staff_removed
```

### Tests

```text
- sensitive tenant action writes audit event
- platform action writes audit event
- audit event stores actor, action, target, reason
```

---

## Final Definition of Done

```text
[ ] `is_superadmin` removed
[ ] platform roles do not bypass tenant endpoints
[ ] user can exist without organisation
[ ] user can create organisation and become owner
[ ] user with active membership cannot create second organisation
[ ] owner cannot transfer ownership
[ ] owner cannot be removed/demoted through tenant API
[ ] owner/admin can update organisation name
[ ] owner/admin can update organisation slug
[ ] owner can invite member/admin
[ ] admin can invite member only
[ ] owner can remove admin/member
[ ] admin can remove member only
[ ] member cannot manage organisation users
[ ] suspended user cannot perform tenant actions
[ ] suspended organisation blocks tenant actions
[ ] platform_staff stored in backend
[ ] platform actions available only through /api/v1/platform/*
[ ] platform actions write audit events
[ ] tests cover role matrix
```
