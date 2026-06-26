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

# DSR erasure orchestrator audit minimisation

## Historical context

This slice wired the DSR-specific audit minimisation provider into the internal
core erasure orchestrator.

## Provider order in this slice

The orchestrator ran providers in this order:

1. `audit.minimise_subject_actor_or_target_identifiers`
2. `outbox.purge_or_scrub_payload`
3. `invites.anonymise_or_purge_subject_references`
4. `users.anonymise_profile`

Audit minimisation ran first because audit rows may be under active legal hold.
If a matching audit row was held, the orchestrator failed before mutating outbox,
invite, or user profile data.

The subject and invite snapshots were captured before mutation so outbox and
invite providers did not lose matching data after the user profile was
anonymised.

## Failure behaviour

Provider failures were returned as a failed orchestration result. The orchestrator
marked the Data Subject Request execution status as `failed` and left the outer
transaction boundary to the caller.

Provider mutations ran inside a nested transaction. If audit minimisation failed,
no outbox, invite, or user profile mutations were applied.

## Superseded scope note

Later slices expanded provider coverage, platform execution, fulfilment, and
retention handling. Use the current DSR documentation and closure checklist for
#328 status.
