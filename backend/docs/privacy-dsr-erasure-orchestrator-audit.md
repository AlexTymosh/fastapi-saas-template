# DSR erasure orchestrator audit minimisation

This slice wires the DSR-specific audit minimisation provider into the internal
core erasure orchestrator.

## Provider order

The orchestrator now runs providers in this order:

1. `audit.minimise_subject_actor_or_target_identifiers`
2. `outbox.purge_or_scrub_payload`
3. `invites.anonymise_or_purge_subject_references`
4. `users.anonymise_profile`

Audit minimisation runs first because audit rows may be under active legal hold.
If a matching audit row is held, the orchestrator should fail before mutating
outbox, invite, or user profile data.

The subject and invite snapshots are still captured before mutation so outbox and
invite providers do not lose matching data after the user profile is anonymised.

## Failure behaviour

Provider failures are returned as a failed orchestration result. The orchestrator
marks the Data Subject Request execution status as `failed` and leaves the outer
transaction boundary to the caller.

Provider mutations run inside a nested transaction. If audit minimisation fails,
no outbox, invite, or user profile mutations are applied.

## Out of scope

This slice does not add public API, worker execution, DSR fulfilment, or retention
purge runners.
