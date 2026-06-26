> Historical implementation-slice note.
>
> This document describes an earlier implementation slice of issue #328.
> It is not the current DSR/privacy source of truth.
>
> Current status is documented in:
>
> - `backend/docs/privacy-dsr.md`
> - `backend/docs/privacy-dsr-328-closure-checklist.md`
> - `backend/docs/current-state.md`

# DSR erasure execution permission boundary

## Historical context

This slice resolved the permission mismatch before approved erasure execution was
exposed through the platform API.

## Problem

The internal erasure execution command allowed privileged staff roles:

- `platform_admin`;
- `compliance_officer`.

The existing `gdpr:erase` permission was intentionally not granted to compliance
officers. Reusing it for the data-subject-request erasure API would have made the
API contract stricter than the command-layer contract.

Using the existing `privacy_requests:review` permission would have been too broad
for a destructive erasure action.

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

The current route:

```text
POST /api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure
```

requires:

```text
privacy_requests:execute_erasure
```

## Superseded scope note

The permission boundary is now part of the implemented platform DSR erasure API.
Use the current DSR documentation and closure checklist for #328 status.
