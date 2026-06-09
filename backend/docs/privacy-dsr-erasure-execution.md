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
- rejects self-erasure execution before providers run;
- delegates to the core erasure orchestrator;
- persists an execution audit event in the same transaction;
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

## Self-erasure guard

The executor must not be the same local user as the DSR subject. Self-execution
is rejected before provider orchestration starts and before the execution audit
row is written.

This prevents a successful self-erasure from creating a final
`data_subject_request_erasure_executed` audit event whose `actor_user_id` still
contains the erased subject's direct user identifier after audit minimisation has
already completed.

## Execution audit trail

Successful and failed orchestration results create an `audit_events` row before
the function returns.

The audit event stores:

- `actor_user_id`: the staff user who executed the erasure;
- `target_type`: `data_subject_request`;
- `target_id`: the DSR id;
- `action`: `data_subject_request_erasure_executed`;
- structured metadata with orchestration status, provider keys, affected rows,
  mutation flag, and optional failure reason code.

Unauthorised attempts, missing-request failures, and self-erasure attempts do not
create this execution audit event because no valid execution was authorised.

## Transaction boundary

The command layer does not commit. Callers should run it inside the existing
application transaction boundary, for example an API route or a background worker
unit of work.

Provider failures are still handled by the orchestrator:

- provider mutations are rolled back through nested transactions;
- the DSR failed execution state can be committed by the outer transaction;
- the execution audit event is persisted by the same outer transaction.

## Out of scope

This slice does not add:

- a public API endpoint;
- a background worker;
- DSR fulfilment transition;
- final retention/purge runners.
