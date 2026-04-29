# Access Control Documentation

This folder defines the target access-control model for the FastAPI SaaS template.

## Scope

The documentation covers:

- user onboarding and organisation creation;
- tenant-level roles and permissions;
- platform-level staff roles and permissions;
- invite and membership rules;
- planned code changes needed to remove `superadmin`;
- audit expectations for sensitive actions.

## Core principle

The project uses two separate authorization planes:

```text
1. Tenant / organisation access
   Users act as owner/admin/member inside one organisation.

2. Platform / back-office access
   Internal staff act through platform-only endpoints.
```

Platform roles must not bypass ordinary tenant endpoints.

```text
Tenant endpoints:   /api/v1/organisations/*
Platform endpoints: /api/v1/platform/*
```

## Documents

| File | Purpose |
|---|---|
| `business-rules.md` | Product and domain rules for users, organisations, memberships, invites, and platform staff |
| `role-matrix.md` | Tenant and platform permission matrices |
| `platform-access.md` | Platform staff model, permissions, bootstrap, and audit rules |
| `implementation-plan.md` | Step-by-step code change plan |
