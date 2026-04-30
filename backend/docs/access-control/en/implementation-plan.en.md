# Access Control Implementation Plan

## Goal

Remove the `superadmin` concept from tenant/business logic and introduce a clean separation between:

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

Platform roles are not tenant roles. Platform staff access is stored in backend (`platform_staff`) and must not be treated as organisation membership. Platform actors must use `/api/v1/platform/*` and must not bypass `/api/v1/organisations/*`.

## PR 1 — Remove `superadmin` bypass from tenant flows

Suggested commit:

```text
🔐 fix(authz): remove superadmin bypass from tenant flows
```

### Files to change

```text
backend/app/core/auth_claims.py
backend/app/organisations/api/organisations.py
backend/app/organisations/services/access.py
```

### Tasks

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

### Add

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
- suspended user may still call GET /api/v1/users/me
- suspended user cannot accept invite
- suspended user cannot create organisation
- suspended user cannot perform platform actions
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

---

## PR 4 — Add membership management

Suggested commit:

```text
👥 feat(memberships): add role management and member removal
```

### Endpoints

```text
GET    /api/v1/organisations/{organisation_id}/directory
GET    /api/v1/organisations/{organisation_id}/memberships
PATCH  /api/v1/organisations/{organisation_id}/memberships/{membership_id}/role
DELETE /api/v1/organisations/{organisation_id}/memberships/{membership_id}
```

### Listing rules

```text
Directory endpoint:
- member/admin/owner can access
- privacy-aware output (display_name, optional public label/avatar)
- no default exposure of internal ids, email, system role, status, or audit metadata

Membership management list:
- admin/owner only
- may include membership_id, user_id, email, tenant role, status
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
- member cannot read memberships management list
- member can read directory
```

---

## PR 5 — Harden invite lifecycle

Suggested commit:

```text
✉️ feat(invites): harden invite lifecycle and revocation rules
```

### Add

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

---

## PR 6 — Add audit trail foundation

Suggested commit:

```text
🧾 feat(audit): record sensitive tenant and platform actions
```

### Add table

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
- ip_address
- user_agent
- created_at
```

Notes:

- `audit_events` must be introduced before any `/api/v1/platform/*` endpoints.
- current tenant-sensitive actions emit events now; future platform actions will reuse the same table.
- `category`, `action`, `target_type` are stored as strings in DB; application code validates via Python enums.
- metadata must stay small and must not include raw tokens, token hashes, full headers, or arbitrary PII.

### Categories

```text
tenant
platform
security
compliance
```

### Audit actions

```text
organisation_updated
organisation_deleted
membership_removed
membership_role_changed
invite_created
invite_revoked
invite_resent
```

---

## PR 7 — Add platform staff foundation

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

---

## PR 8 — Add bootstrap command for first platform admin

Suggested commit:

```text
🔑 chore(platform): add bootstrap command for first platform admin
```

### Add

```text
python -m app.commands.create_platform_admin --email <email>
```

### Rules

```text
- command must require existing local user
- creates platform_staff role=platform_admin
- writes audit event in audit_events
- no public self-service platform admin creation
```

---

## PR 9 — Add audited platform administration endpoints

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

### Rules

```text
- all endpoints must require require_platform_permission(permission)
- all sensitive actions must emit audit_events records
- platform endpoints must not create implicit tenant membership
```

---

## PR 10 — Remove JWT platform roles from authorization path (if still present)

Suggested commit:

```text
🧹 refactor(authz): remove JWT platform roles from authorization path
```

### Tasks

```text
- stop using JWT-only platform role claims as authorization source
- rely on backend platform_staff + permissions as source of truth
- keep JWT for authentication only
- preserve tenant/platform separation tests
```

---

## Final Definition of Done

```text
[ ] `is_superadmin` removed
[ ] platform roles do not bypass tenant endpoints
[ ] user can exist without organisation
[ ] user can create organisation and become owner
[ ] user with active membership cannot create second organisation
[ ] platform-created organisation requires explicit initial owner assignment
[ ] owner cannot transfer ownership
[ ] owner cannot be removed/demoted through tenant API
[ ] owner/admin can update organisation name
[ ] owner/admin can update organisation slug
[ ] owner/admin can access memberships management list
[ ] member can access organisation directory only (not memberships management list)
[ ] owner can invite member/admin
[ ] admin can invite member only
[ ] owner can remove admin/member
[ ] admin can remove member only
[ ] member cannot manage organisation users
[ ] suspended user cannot perform tenant actions
[ ] suspended organisation blocks tenant actions
[ ] platform_staff stored in backend
[ ] require_platform_permission(permission) introduced
[ ] audit_events introduced for tenant + platform sensitive actions
[ ] platform actions available only through /api/v1/platform/*
[ ] tests cover tenant/platform separation and role matrix
```

- Platform foundation implemented: `platform_staff`, platform permissions/dependency, and bootstrap command.
