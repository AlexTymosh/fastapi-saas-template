# Role Matrix

## 1. Tenant roles

Tenant roles are scoped to one organisation.

```text
owner
admin
member
```

A standalone user has no tenant role.

## 2. Tenant permission matrix

| Action | Standalone user | Member | Admin | Owner |
|---|---:|---:|---:|---:|
| Register and exist without organisation | Yes | N/A | N/A | N/A |
| Create organisation | Yes, if no active membership | No | No | No |
| View own organisation | No | Yes | Yes | Yes |
| View organisation directory (`GET /directory`) | No | Yes | Yes | Yes |
| View membership management list (`GET /memberships`) | No | No | Yes | Yes |
| Update organisation name | No | No | Yes | Yes |
| Update organisation slug | No | No | Yes | Yes |
| Delete organisation | No | No | No | Yes |
| Invite member | No | No | Yes | Yes |
| Invite admin | No | No | No | Yes |
| Invite owner | No | No | No | No |
| Promote member to admin | No | No | No | Yes |
| Demote admin to member | No | No | No | Yes |
| Promote anyone to owner | No | No | No | No |
| Demote owner | No | No | No | No |
| Remove member | No | No | Yes | Yes |
| Remove admin | No | No | No | Yes |
| Remove owner | No | No | No | No |
| Transfer ownership | No | No | No | No |

## 3. Directory vs membership management data scope

| Endpoint | Member | Admin | Owner | Data scope |
|---|---:|---:|---:|---|
| `GET /api/v1/organisations/{organisation_id}/directory` | Yes | Yes | Yes | Minimal colleague directory (`display_name` and `tenant_role` (`owner`/`admin`/`member`). No default exposure of internal `user_id`, `membership_id`, email, status fields, or audit/security metadata. |
| `GET /api/v1/organisations/{organisation_id}/memberships` | No | Yes | Yes | Administrative membership view for management: may include `membership_id`, `user_id`, email, tenant role, and status fields. |

## 4. Invite matrix

| Invite target role | Member can invite | Admin can invite | Owner can invite |
|---|---:|---:|---:|
| member | No | Yes | Yes |
| admin | No | No | Yes |
| owner | No | No | No |

## 5. Membership management matrix

| Target membership | Admin can remove | Owner can remove | Owner can change role |
|---|---:|---:|---:|
| member | Yes | Yes | member -> admin |
| admin | No | Yes | admin -> member |
| owner | No | No | No |

## 6. Platform roles

Platform roles are not tenant roles.

```text
platform_admin
support_agent
compliance_officer
```

## 7. Platform permission matrix

| Permission / capability | Support agent | Compliance officer | Platform admin |
|---|---:|---:|---:|
| `users:read` | No | No | Yes |
| `users:read_limited` | Yes | Yes | Yes |
| `users:suspend` | No | No | Yes |
| `users:restore` | No | No | Yes |
| `users:correct_profile` | No | No | Yes |
| `organisations:read` | No | No | Yes |
| `organisations:read_limited` | Yes | Yes | Yes |
| `organisations:suspend` | No | No | Yes |
| `organisations:restore` | No | No | Yes |
| `organisations:correct_profile` | No | No | Yes |
| `organisations:emergency_owner_correction` | No | No | Yes |
| `platform_staff:manage` | No | No | Yes |
| `audit:read` | No | Yes | Yes |
| `audit:read_limited` | Yes, redacted limited view only | Yes, redacted limited view available | Yes |
| `privacy_requests:read` | No | Yes | Yes |
| `privacy_requests:review` | No | Yes | Yes |
| `privacy_requests:execute_erasure` | No | Yes | Yes |
| `privacy_export_artifacts:read` | No | Yes | Yes |
| `privacy_export_artifacts:manage` | No | Yes | Yes |

## 8. Critical separation rule

Platform roles must not grant access to ordinary tenant endpoints.

Example:

```text
A platform_admin who is not a member of organisation X
must receive 403 from:

GET /api/v1/organisations/{organisation_id}
```

The same actor may use a dedicated platform endpoint:

```text
GET /api/v1/platform/organisations/{organisation_id}
```

- Platform matrix is now enforced by backend `platform_staff` role-to-permission mapping.

- Platform access is DB-backed via `platform_staff`; JWT roles must never grant request-time backend permissions and may only become future controlled JIT provisioning input for local DB records.
- Platform actors can act only via `/api/v1/platform/*` and do not bypass tenant `/api/v1/organisations/*` endpoints.
- Platform write actions require a non-blank reason, are audited, and self-suspension is forbidden.
- Last-platform-admin hardening is deferred to future platform staff-management stage.

## 10. Platform full and limited read views

Platform read access is intentionally split into full operational views and limited support/compliance views:

| Endpoint | Support agent | Compliance officer | Platform admin | Data scope |
|---|---:|---:|---:|---|
| `GET /api/v1/platform/users` | No | No | Yes | Full platform user DTO for operational administration. |
| `GET /api/v1/platform/users/limited` | Yes | Yes | Yes | Limited user DTO with `id`, name fields, `status`, and `created_at`; full email, external identity IDs, suspension details, onboarding state, and identity-provider internals are omitted. |
| `GET /api/v1/platform/organisations` | No | No | Yes | Full platform organisation DTO for operational administration; existing admin include-deleted visibility is preserved. |
| `GET /api/v1/platform/organisations/limited` | Yes | Yes | Yes | Limited organisation DTO with `id`, `name`, `slug`, `status`, and `created_at`; deleted organisations, suspension reasons, owner internals, membership internals, and audit metadata are omitted. |
| `GET /api/v1/platform/audit-events` | No | Yes | Yes | Full audit view according to platform permissions. |
| `GET /api/v1/platform/audit-events/limited` | Yes | Yes | Yes | Redacted audit view; raw metadata, IP address, user-agent, free-text reason, and direct actor identifiers are omitted. |

Platform list endpoints cap `limit` at 100 and require non-negative `offset` values for stable admin pagination. Full user list search (`q`) may match email, first name, and last name. Limited user list search (`q`) is intentionally restricted to first name and last name so hidden email addresses cannot be inferred through partial search probes; limited user lists provide `exact_email` only for exact-match support workflows, and limited responses still do not expose email or email-verification fields. Organisation full and limited search covers `name` and `slug`; the full platform organisation view preserves existing include-deleted operational visibility, while the limited organisation view excludes soft-deleted organisations by default.

The limited DTOs are designed for future admin frontend screens where support or compliance users need safe discovery workflows without receiving operationally sensitive fields.

## 11. Platform OpenAPI and permission test contract

Platform routes under `/api/v1/platform/*` are covered by OpenAPI contract tests so future admin frontend clients can be generated from stable route metadata. The contract expects unique operation IDs, explicit platform tags, documented success response models, and route-level rate-limit policy metadata for platform read and write endpoints.

The platform BFLA permission matrix is covered by security tests for unauthenticated requests, authenticated users without local projections, active local users without platform staff rows, suspended local users, support agents, compliance officers, platform admins, and suspended platform staff. Denied platform requests must return the generic platform access denial response and denied writes must not create audit events.
