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

Critical rule: platform roles are not tenant roles. Platform actors must use `/api/v1/platform/*` and must not bypass `/api/v1/organisations/*`.

## PR 1 — Remove `superadmin` bypass from tenant flows

Suggested commit:

```text
🔐 fix(authz): remove superadmin bypass from tenant flows
```

### Tasks

- Remove `is_superadmin()`.
- Remove superadmin/platform bypass branches from tenant access checks.
- Keep self-service organisation creation through onboarding service.
- Add regression tests for tenant/platform separation.

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
- suspended user cannot accept invite
- suspended user cannot create organisation
- suspended organisation blocks ordinary tenant actions
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

### Rules

```text
- owner can update name and slug
- admin can update name and slug
- member cannot update name or slug
- standalone user cannot update organisation name or slug
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

### Rules

```text
Directory endpoint:
- member/admin/owner allowed
- privacy-aware fields only (no internal IDs/email by default)

Membership list endpoint:
- admin/owner allowed
- member forbidden
- administrative fields allowed for management
```

---

## PR 5 — Harden invite lifecycle

Suggested commit:

```text
✉️ feat(invites): harden invite lifecycle and revocation rules
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
🧾 feat(audit): add audit_events foundation for tenant and platform actions
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
- created_at
```

### Categories

```text
tenant
platform
security
compliance
```

---

## PR 7 — Add platform staff foundation

Suggested commit:

```text
🛡️ feat(platform): add platform_staff model and permission dependency
```

### Add

```text
platform_staff table
require_platform_permission(permission)
```

---

## PR 8 — Add bootstrap command for first platform admin

Suggested commit:

```text
🧰 feat(platform): add bootstrap command for initial platform admin
```

---

## PR 9 — Add audited platform administration endpoints

Suggested commit:

```text
🛠️ feat(platform): add audited platform administration endpoints
```

### Requirements

```text
- endpoints live under /api/v1/platform/*
- require require_platform_permission(permission)
- platform-created organisation requires explicit initial owner assignment
  (initial_owner_user_id or initial_owner_email)
- all sensitive actions write audit_events records
```

---

## PR 10 — Remove JWT platform roles from authorization path, if still present

Suggested commit:

```text
🧹 refactor(authz): remove JWT platform-role shortcuts in favour of backend platform_staff
```

---

## Final Definition of Done

```text
[ ] is_superadmin removed
[ ] platform roles do not bypass tenant endpoints
[ ] user can exist without organisation
[ ] user can create organisation and becomes owner
[ ] platform-created organisation requires explicit initial owner assignment
[ ] user with active membership cannot create second organisation
[ ] owner cannot transfer ownership
[ ] owner cannot be removed/demoted through tenant API
[ ] owner/admin can update organisation name
[ ] owner/admin can update organisation slug
[ ] owner/admin can read membership management list
[ ] member can read directory but cannot read membership management list
[ ] owner can invite member/admin
[ ] admin can invite member only
[ ] owner can remove admin/member
[ ] admin can remove member only
[ ] suspended user cannot perform tenant actions
[ ] suspended organisation blocks tenant actions
[ ] platform_staff stored in backend
[ ] require_platform_permission(permission) used for platform endpoints
[ ] platform actions available only through /api/v1/platform/*
[ ] audit_events introduced (shared tenant/platform audit model)
[ ] regression tests cover tenant/platform separation
```
