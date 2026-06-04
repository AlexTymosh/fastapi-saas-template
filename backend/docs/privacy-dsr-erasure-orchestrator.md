# DSR core erasure orchestrator

This slice adds the internal orchestration contract for the currently implemented
core erasure providers:

1. `outbox.purge_or_scrub_payload`
2. `invites.anonymise_or_purge_subject_references`
3. `users.anonymise_profile`

The orchestrator is intentionally not exposed through public API or a worker yet.
It does not commit the transaction and does not fulfil the Data Subject Request.

## Why this exists

The individual providers are safe in isolation, but they must be run in a fixed
order.

The workflow needs a pre-erasure snapshot before direct identifiers are removed:

- subject email;
- subject-linked invite ids.

Those values are needed by the outbox and invite providers. If user or invite
anonymisation ran first without passing snapshots, later providers could lose the
ability to find subject-linked rows.

## Execution order

The order is:

```text
snapshot subject_email/invite_ids → outbox → invites → users
```

Outbox is first because it may contain delivery-only personal data and encrypted
invite token material. It also blocks execution when subject-linked rows are
currently `processing`, because the worker may already have decrypted delivery
material.

Invites are second because invite email and token material should be minimised
before the user profile loses its original email.

The user profile is last because it removes the direct subject identifiers from
the local account projection.

## Transaction behaviour

The orchestrator uses a nested transaction around provider mutations.

If a provider fails, provider mutations are rolled back and the DSR execution
status is marked as `failed` with a safe reason code. The caller still controls
the outer transaction boundary.

On success, the DSR execution status is marked as `ready`.

## Out of scope

This slice does not implement:

- platform API endpoints;
- background worker execution;
- audit minimisation;
- fulfilment of `erase` requests;
- retention/purge runners;
- worker lock/dispatch coordination beyond blocking in-flight processing rows.

The next slice should either add controlled audit minimisation or wire this
orchestrator into a worker/API path with explicit retry semantics.
