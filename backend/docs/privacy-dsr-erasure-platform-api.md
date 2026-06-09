# DSR erasure platform API

This slice exposes the approved erase DSR execution path through a platform-only
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
- provider orchestration;
- durable execution audit trail;
- transaction-safe failure handling;
- execution error mapping to application errors.

## Error mapping

The API route does not catch or translate execution business-flow errors. The
service/command boundary maps execution errors and the global exception handlers
format them as Problem Details responses:

- missing DSR: `404`;
- stale or invalid executor state: `403`;
- ineligible DSR or orchestration precondition failure: `409`.

Provider execution failures that are represented as a failed orchestration result
are returned as a `200` response with the DSR `execution_status` set to `failed`.

## Out of scope

This slice does not add:

- background worker execution;
- automatic fulfilment transition;
- retention/purge runners;
- final issue #328 closure checklist.
