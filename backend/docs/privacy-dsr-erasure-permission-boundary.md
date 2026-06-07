# DSR erasure execution permission boundary

This slice resolves the permission mismatch before exposing approved erasure
execution through a platform API endpoint.

## Problem

The internal erasure execution command allows privileged staff roles:

- `platform_admin`;
- `compliance_officer`.

The existing `gdpr:erase` permission is intentionally not granted to compliance
officers. Reusing it for the future data-subject-request erasure API would make
the API contract stricter than the command-layer contract.

Using the existing `privacy_requests:review` permission would be too broad for a
destructive erasure action.

## Decision

Add a dedicated permission:

```text
privacy_requests:execute_erasure
```

Grant it to:

- `platform_admin`;
- `compliance_officer`.

Do not grant it to:

- `support_agent`.

Keep `gdpr:erase` unchanged. It remains separate from DSR workflow execution and
is not reused for the platform DSR erasure endpoint.

## Why this is safer

The permission name matches the actual capability: executing an approved privacy
request erasure. It avoids overloading the generic GDPR erase permission and
keeps destructive erasure separate from ordinary request review actions.

Future API route:

```text
POST /api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure
```

should require:

```text
privacy_requests:execute_erasure
```

## Out of scope

This slice does not add:

- the API endpoint;
- worker execution;
- fulfilment transition;
- retention or purge runners.
