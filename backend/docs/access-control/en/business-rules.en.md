# Business Rules

## 1. User registration and onboarding

### Rules

1. A user may register without an organisation.
2. A registered user without active membership is a standalone user.
3. A standalone active user may create an organisation.
4. When a user creates an organisation, the backend must:
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
2. If created by a standalone tenant user, the creator becomes `owner`.
3. If created by a platform-level administrative action:
   - the platform actor must not become a tenant `owner` automatically;
   - platform roles must not create tenant membership implicitly;
   - the endpoint must require explicit initial owner assignment via `initial_owner_user_id` or `initial_owner_email`.
4. Temporary ownerless creation is a special bootstrap/operational state only and must not be the default.
5. Organisation ownership cannot be transferred through tenant/business API.
6. The `owner` cannot be removed through tenant/business API.
7. The `owner` cannot be demoted to `admin` or `member`.
8. Only the `owner` may delete the organisation.
9. `owner` and `admin` may update organisation `name` and `slug`.
10. `member` and standalone user may not update organisation `name` or `slug`.
11. A suspended organisation must block ordinary tenant actions.
12. A deleted organisation must be inaccessible through ordinary tenant endpoints.

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

## 3. Membership rules

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
- view organisation directory;
- view membership management list;
- update organisation name;
- update organisation slug;
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
- view organisation directory;
- view membership management list;
- update organisation name;
- update organisation slug;
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
- view organisation directory.

The `member` may not:

- view membership management list;
- update organisation name or slug;
- invite users;
- manage memberships;
- delete organisation;
- perform platform actions.

### Directory vs membership management list

#### Organisation directory

Endpoint concept:

```text
GET /api/v1/organisations/{organisation_id}/directory
```

Access:

- member: yes
- admin: yes
- owner: yes

Purpose: minimal, privacy-aware colleague directory for organisation participants.

Allowed example fields:

- display_name
- role_label or public title (if needed)
- optional avatar_url in the future

Do not expose by default:

- internal `user_id`
- `membership_id`
- email
- system membership role (`owner` / `admin` / `member`) unless explicitly required by future product logic
- status fields
- audit/security metadata

#### Membership management list

Endpoint concept:

```text
GET /api/v1/organisations/{organisation_id}/memberships
```

Access:

- member: no
- admin: yes
- owner: yes

Purpose: administrative view for managing memberships and roles.

May expose:

- `membership_id`
- `user_id`
- email
- tenant role
- `is_active` / status fields (if required for management)

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

Platform access must be stored in the backend, not treated as a normal organisation membership.

Platform actions must go through:

```text
/api/v1/platform/*
```

Platform actions must not bypass:

```text
/api/v1/organisations/*
```

A `platform_admin` who is not a member of organisation X must receive `403` from:

```text
GET /api/v1/organisations/{organisation_id}
```

The same actor may use:

```text
GET /api/v1/platform/organisations/{organisation_id}
```

### Platform admin

May:

- suspend/restore users;
- suspend/restore organisations;
- manage platform staff;
- read audit events;
- perform audited emergency corrections.

### Support agent

May:

- read limited user information;
- read limited organisation information;
- help resolve support cases.

Must not:

- suspend users;
- suspend organisations;
- manage platform staff;
- access unrestricted audit events.

### Compliance officer

May:

- read audit events;
- perform or request GDPR-related workflows;
- read limited user/organisation information when required.

Must not:

- manage organisation memberships;
- perform ordinary tenant actions;
- manage platform staff unless explicitly allowed.

---

## 6. Audit rules

Audit events (`audit_events`) should be written for:

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


## Suspended user boundary

- suspended user may still access `/api/v1/users/me` for identity/profile visibility;
- suspended user must not perform tenant actions;
- suspended user must not perform platform actions.


## JWT roles boundary

External JWT roles are not a backend authorization source. Claims like `superadmin`, `platform_admin`, `realm_access.roles`, `resource_access`, or direct `roles` must not grant tenant or platform permissions in backend authorization. Future platform authorization must use backend `platform_staff` records.
