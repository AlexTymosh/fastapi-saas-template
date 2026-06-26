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

# DSR erasure platform API

## Historical context

This slice exposed the approved erase DSR execution path through a platform-only
API endpoint.

## Endpoint

```text
POST /api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure
```

The endpoint uses the dedicated platform permission:

```text
privacy_requests:execute_erasure
```

This keeps destructive erasure separate from generic request review permission.

## Execution flow

The route:

1. requires a rate-limited platform write context;
2. requires `PlatformPermission.PRIVACY_REQUESTS_EXECUTE_ERASURE`;
3. delegates to `DataSubjectRequestService`;
4. returns the updated platform DSR representation.

The service and command layers remain responsible for:

- executor active-user and active-staff checks;
- DSR row locking;
- self-erasure rejection before provider orchestration;
- provider orchestration;
- durable execution audit trail;
- transaction-safe failure handling;
- execution error mapping to application errors;
- automatic transition of successfully executed approved erase DSRs to
  `fulfilled`.

## Error mapping

The API route does not catch or translate execution business-flow errors. The
service/command boundary maps execution errors and the global exception handlers
format them as Problem Details responses:

- missing DSR: `404`;
- stale or invalid executor state: `403`;
- self-erasure execution attempt: `403`;
- ineligible DSR or orchestration precondition failure: `409`.

Successful erasure execution returns `200` with `status=fulfilled` and
`execution_status=ready`.

Provider execution failures that are represented as failed orchestration results
return `200` with `status=approved` and `execution_status=failed`, leaving the
request open for staff investigation or retry.

## Superseded scope note

The platform erasure endpoint is now part of the implemented backend DSR scope.
Use the current DSR documentation and closure checklist for #328 status.
