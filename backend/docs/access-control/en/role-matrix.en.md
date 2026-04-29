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

## 3. Invite matrix

| Invite target role | Member can invite | Admin can invite | Owner can invite |
|---|---:|---:|---:|
| member | No | Yes | Yes |
| admin | No | No | Yes |
| owner | No | No | No |

## 4. Membership management matrix

| Target membership | Admin can remove | Owner can remove | Owner can change role |
|---|---:|---:|---:|
| member | Yes | Yes | member -> admin |
| admin | No | Yes | admin -> member |
| owner | No | No | No |

## 5. Platform roles

Platform roles are not tenant roles.

```text
platform_admin
support_agent
compliance_officer
```

## 6. Platform permission matrix

| Action | Support agent | Compliance officer | Platform admin |
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

## 7. Critical separation rule

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
