# DSR erasure execution command layer

This slice adds an internal command-layer entry point for approved erasure DSRs.

The previous slices implemented and wired the core providers:

- audit minimisation;
- outbox payload scrubbing;
- invite anonymisation/minimisation;
- user profile anonymisation.

This slice does not expose a public API endpoint and does not create a worker.
It adds the safe service boundary that future API/worker code should call.

## Entry point

```text
execute_approved_erasure_request_by_staff(...)
```

The function:

- locks and authorises the platform staff executor;
- verifies that the linked local user is still active;
- locks the DSR row;
- delegates to the core erasure orchestrator;
- returns a structured execution result;
- does not commit.

## Authorisation

Only active platform staff with an active linked local `users` row and one of
these roles may execute an erasure:

- `platform_admin`;
- `compliance_officer`.

A support agent is intentionally not enough for destructive erasure execution.

Both checks are required:

- `platform_staff.status == active`;
- `users.status == active`.

This mirrors the platform actor access path and prevents a suspended local user
from executing destructive erasure through a worker or other non-API caller that
passes `executor_user_id` directly.

## Transaction boundary

The command layer does not commit. Callers should run it inside the existing
application transaction boundary, for example an API route or a background worker
unit of work.

Provider failures are still handled by the orchestrator:

- provider mutations are rolled back through nested transactions;
- the DSR failed execution state can be committed by the outer transaction.

## Out of scope

This slice does not add:

- a public API endpoint;
- a background worker;
- DSR fulfilment transition;
- final retention/purge runners.
