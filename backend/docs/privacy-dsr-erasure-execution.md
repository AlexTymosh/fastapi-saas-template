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

# DSR erasure execution command layer

## Current status

This document describes the internal command-layer entry point used for approved
erasure DSR execution.

The command layer is part of the current erase execution flow. It is called by
the service/API boundary and records execution evidence while leaving the outer
transaction boundary to the caller.

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

## Self-erasure guard

The executor must not be the same local user as the DSR subject. Self-execution
is rejected before provider orchestration starts and before the execution audit
row is written.

This prevents the final erasure execution audit event from retaining the erased
subject as its own actor after audit minimisation has already run.

## Execution audit trail

Successful and failed orchestration results create an `audit_events` row before
the function returns.

The audit event stores:

- `actor_user_id`: the staff user who executed the erasure;
- `target_type`: `data_subject_request`;
- `target_id`: the DSR id;
- `action`: `data_subject_request_erasure_executed`;
- structured metadata with orchestration status, provider keys, affected rows,
  mutation flag, provider decisions, and optional failure reason code.

## Fulfilment transition

The command layer executes erasure and persists execution audit evidence.

Platform/API callers should use `DataSubjectRequestService`, which maps command
errors and automatically moves an approved erase DSR to `fulfilled` after a
successful `ready` execution state.

Failed orchestration results keep the DSR in `approved` with
`execution_status=failed` so staff can investigate or retry after the blocking
condition is resolved.
