# Business Rules

## 1. User registration and onboarding

### Rules

1. A user may register without an organisation.
2. A registered user without active membership is a standalone user.
3. A standalone active user may create an organisation.
4. When a standalone user creates an organisation, the backend must:
   - create or refresh the local user projection;
   - create the organisation;
   - create an active membership for the creator;
   - assign the creator the `owner` role;
   - mark onboarding as completed.
5. A user may have at most one active organisation membership.
6. Creating an organisation should require `email_verified=true`.
7. A suspended user must not be able to:
   - create an organisation;
   - accept an invite;
   - create an invite;
   - update organisation data;
   - manage memberships;
   - perform platform actions.

### Not a role

`standalone user` is not a role. It is a user state:

```text
User exists
AND user.status = active
AND no active membership exists
```

---

## 2. Organisation rules

### Organisation lifecycle

1. An organisation is created by a standalone user or by a platform-level administrative action.
2. If a standalone tenant user creates an organisation, that creator becomes `owner`.
3. If an organisation is created by a platform-level administrative action, the platform actor must not become a tenant owner automatically.
4. Platform roles must not create tenant membership implicitly.
5. Platform creation endpoint must require explicit initial owner assignment (`initial_owner_user_id` or `initial_owner_email`).
6. A temporarily ownerless organisation is allowed only as a special bootstrap/operational state and must not be the default flow.
7. Organisation ownership cannot be transferred through tenant/business API.
8. The `owner` cannot be removed through tenant/business API.
9. The `owner` cannot be demoted to `admin` or `member`.
10. Only the `owner` may delete the organisation.
11. `owner` and `admin` may update organisation `name`.
12. `owner` and `admin` may update organisation `slug`.
13. A `member` cannot update organisation `name` or `slug`.
14. A standalone user cannot update organisation `name` or `slug`.
15. A suspended organisation must block ordinary tenant actions.
16. A deleted organisation must be inaccessible through ordinary tenant endpoints.

### Status model

Recommended statuses:

```text
active
suspended
```

Do not add `deleted` as a status while `deleted_at` already exists.

```text
status = active / suspended
deleted_at = soft deletion marker
```

---

## 3. Membership and directory rules

### Roles

```text
owner
admin
member
```

### General rules

1. A user may have only one active membership.
2. Membership belongs to exactly one organisation.
3. Membership role is scoped to the organisation only.
4. Organisation roles are not platform roles.
5. Platform staff roles must not grant tenant membership rights.

### Owner rules

The `owner` may:

- view organisation;
- update organisation name;
- update organisation slug;
- read organisation directory;
- read membership management list;
- invite members;
- invite admins;
- promote member to admin;
- demote admin to member;
- remove admin;
- remove member;
- delete organisation.

The `owner` may not:

- transfer ownership;
- demote themselves or another owner;
- remove themselves or another owner through tenant API;
- invite another owner.

### Admin rules

The `admin` may:

- view organisation;
- update organisation name;
- update organisation slug;
- read organisation directory;
- read membership management list;
- invite members;
- remove members.

The `admin` may not:

- invite admins;
- promote members to admins;
- demote admins;
- remove admins;
- remove owner;
- delete organisation;
- transfer ownership.

### Member rules

The `member` may:

- view organisation;
- read organisation directory.

The `member` may not:

- update organisation;
- invite users;
- read membership management list;
- manage memberships;
- delete organisation;
- perform platform actions.

### Tenant endpoint concepts

#### A) Organisation directory

```text
GET /api/v1/organisations/{organisation_id}/directory
```

Access:

- member: yes;
- admin: yes;
- owner: yes.

Purpose:

- Minimal colleague directory for organisation participants.
- Privacy-aware response, without administrative/internal fields by default.

Allowed example fields:

- `display_name`;
- `role_label` (public title only, if needed);
- optional `avatar_url` in the future.

Do not expose by default:

- `internal user_id`;
- `membership_id`;
- `email`;
- system role (`owner`/`admin`/`member`) unless explicitly required by future product logic;
- `status`;
- audit/security metadata.

#### B) Membership management list

```text
GET /api/v1/organisations/{organisation_id}/memberships
```

Access:

- member: no;
- admin: yes;
- owner: yes.

Purpose:

- Administrative view for managing memberships and roles.

May expose:

- `membership_id`;
- `user_id`;
- `email`;
- tenant role;
- `is_active` / status fields, if required for management.

---

## 4. Invite rules

1. Invite tokens must be stored only as hashes.
2. Invite acceptance must use a request body, not a token path parameter.
3. Invite must have expiry.
4. Expired invites cannot be accepted.
5. Revoked invites cannot be accepted.
6. Accepted invites cannot be reused.
7. Invite acceptance must require:
   - valid token;
   - matching email;
   - `email_verified=true`;
   - active user;
   - active organisation.
8. `owner` may invite `member` and `admin`.
9. `admin` may invite only `member`.
10. `member` may not invite users.
11. No one may invite `owner` through ordinary invite flow.
12. There must not be duplicate pending invites for the same email in the same organisation.
13. Invite creation and invite acceptance must be rate-limited.
14. Invite revocation and resend should be audited.

---

## 5. Platform staff rules

Platform roles are separate from organisation roles.

Recommended roles:

```text
platform_admin
support_agent
compliance_officer
```

Platform staff access must be stored in backend data and must not be treated as organisation membership.

Platform actions must go through:

```text
/api/v1/platform/*
```

Platform actions must not bypass:

```text
/api/v1/organisations/*
```

Example:

```text
A platform_admin who is not a member of organisation X
must receive 403 from:
GET /api/v1/organisations/{organisation_id}

The same actor may use:
GET /api/v1/platform/organisations/{organisation_id}
```

---

## 6. Audit rules

Use a shared audit table for tenant and platform sensitive actions:

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

Audit events should be written for:

- organisation name changed;
- organisation slug changed;
- organisation deleted;
- member removed;
- membership role changed;
- invite created;
- invite revoked;
- invite resent;
- user suspended/restored;
- organisation suspended/restored;
- platform staff created/removed/suspended;
- GDPR export/anonymisation actions;
- emergency data correction.
