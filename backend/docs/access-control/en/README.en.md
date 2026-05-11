# Access Control Documentation

This folder defines the target access-control model for the FastAPI SaaS template.

## Scope

The documentation covers:

- user onboarding and organisation creation;
- tenant-level roles and permissions;
- platform-level staff roles, identity, and permissions;
- invite and membership rules;
- completed removal of legacy global-administrator bypass logic;
- audit expectations for sensitive actions.

## Core principle

The project uses two separate authorization planes:

```text
1. Tenant / organisation access
   Users act as owner/admin/member inside one organisation.

2. Platform / back-office access
   Internal staff act through platform-only endpoints.
```

Platform roles are not tenant roles and must not bypass ordinary tenant endpoints.
Authorization is DB-driven: tenant authorization is resolved from local memberships, and platform authorization is resolved from the backend `platform_staff` table. External IdP roles from direct `roles`, `realm_access`, `resource_access`, or similar JWT claims must never grant tenant or platform permissions directly at request time. They may only be used in the future as input for controlled, idempotent, audited JIT provisioning that writes local DB records before permissions are granted.

```text
Tenant endpoints:   /api/v1/organisations/*
Platform endpoints: /api/v1/platform/*, including /api/v1/platform/me for safe platform identity
```

A `platform_admin` who is not a member of organisation X must receive `403` from:

```text
GET /api/v1/organisations/{organisation_id}
```

The same actor may access:

```text
GET /api/v1/platform/organisations/{organisation_id}
```

Authorization source of truth:

- Keycloak is the identity/authentication provider and JWT claims are identity input (`sub`, email, profile claims).
- Backend validates access tokens and maps identity claims into a local user projection.
- Tenant authorization uses local user projection + user status + organisation membership + explicit permission dependencies.
- Platform authorization uses the backend `platform_staff` table.
- External JWT roles such as `platform_admin`, `owner`, `admin`, `member`, or legacy `superadmin` must not grant tenant or platform permissions in backend logic.

## Documents

| File | Purpose |
|---|---|
| `business-rules.en.md` | Product and domain rules for users, organisations, memberships, invites, and platform staff |
| `role-matrix.en.md` | Tenant and platform permission matrices |
| `platform-access.en.md` | Platform staff model, permissions, bootstrap, and audit rules |
| `implementation-plan.en.md` | Step-by-step code change plan |
