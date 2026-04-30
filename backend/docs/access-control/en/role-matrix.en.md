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
| `GET /api/v1/organisations/{organisation_id}/directory` | Yes | Yes | Yes | Minimal colleague directory (`display_name`, optional public role label, optional avatar in future). No default exposure of internal `user_id`, `membership_id`, email, system role, statuses, or audit/security metadata. |
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
| `audit:read_limited` | Optional, support-case scoped only | No | Yes |
| `gdpr:export` | No | Yes | Yes |
| `gdpr:erase` | No | With approval / explicit workflow | Yes |

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


## Invite delivery note
Current invite delivery is best-effort/dev foundation: invite and audit event are persisted first; token delivery failures are logged and do not expose raw tokens. Production should move delivery to outbox/event worker + email provider integration.


## Organisation directory contract
`GET /api/v1/organisations/{organisation_id}/directory` is available for member/admin/owner and returns only `display_name` and `tenant_role` (owner/admin/member). Internal IDs, emails, statuses, and audit/security metadata are not returned.

`GET /api/v1/organisations/{organisation_id}/memberships` remains admin/owner-only management view and may include membership_id, user_id, email, role, status.


## Enum storage policy
Future domain enum-like fields should use explicit string storage with DB check constraints unless there is a strong reason to use SQLAlchemy `Enum(native_enum=False)`.


## Reason policy
Tenant destructive/revocation actions currently accept optional `reason` and write it to audit events. Future platform write actions should require `reason`.
