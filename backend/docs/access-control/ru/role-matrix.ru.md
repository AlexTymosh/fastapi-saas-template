# Матрица ролей

## 1. Tenant roles

Tenant roles ограничены областью одной организации.

```text
owner
admin
member
```

Standalone user не имеет tenant role.

## 2. Матрица tenant permissions

| Действие | Standalone user | Member | Admin | Owner |
|---|---:|---:|---:|---:|
| Register and exist without organisation | Yes | N/A | N/A | N/A |
| Create organisation | Yes, if no active membership | No | No | No |
| View own organisation | No | Yes | Yes | Yes |
| View membership list | No | Yes | Yes | Yes |
| Update organisation name | No | No | No | Yes |
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

## 3. Матрица invites

| Invite target role | Member can invite | Admin can invite | Owner can invite |
|---|---:|---:|---:|
| member | No | Yes | Yes |
| admin | No | No | Yes |
| owner | No | No | No |

## 4. Матрица управления memberships

| Target membership | Admin can remove | Owner can remove | Owner can change role |
|---|---:|---:|---:|
| member | Yes | Yes | member -> admin |
| admin | No | Yes | admin -> member |
| owner | No | No | No |

## 5. Platform roles

Platform roles не являются tenant roles.

```text
platform_admin
support_agent
compliance_officer
```

## 6. Матрица platform permissions

| Действие | Support agent | Compliance officer | Platform admin |
|---|---:|---:|---:|
| Read limited user info | Yes | Yes | Yes |
| Read limited organisation info | Yes | Yes | Yes |
| Suspend user | No | No | Yes |
| Restore user | No | No | Yes |
| Suspend organisation | No | No | Yes |
| Restore organisation | No | No | Yes |
| Correct erroneous user data | No | No | Yes |
| Correct erroneous organisation data | No | No | Yes |
| Read audit events | Limited / No | Yes | Yes |
| Manage platform staff | No | No | Yes |
| GDPR export | No | Yes | Yes |
| GDPR erase/anonymise | No | With approval | Yes |
| Emergency owner correction | No | No | Yes, audited only |

## 7. Критическое правило разделения

Platform roles не должны давать доступ к обычным tenant endpoints.

Пример:

```text
A platform_admin who is not a member of organisation X
must receive 403 from:

GET /api/v1/organisations/{organisation_id}
```

Этот же actor может использовать отдельный platform endpoint:

```text
GET /api/v1/platform/organisations/{organisation_id}
```

- `GET /api/v1/users/me` остаётся доступным для suspended users и пользователей в suspended organisations; tenant-scoped действия остаются заблокированными.
