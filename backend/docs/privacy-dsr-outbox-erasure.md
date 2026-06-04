# DSR outbox erasure provider

This slice adds the controlled mutation provider for:

- `outbox.purge_or_scrub_payload`

The provider is intentionally narrow. It only scrubs subject-linked outbox
payloads for approved `erase` Data Subject Requests. It does not update DSR
execution state, does not commit transactions, and is not wired into public API
or workers yet.

## Why this exists

Outbox rows may contain delivery-only personal data and secrets in
`payload_json`, for example invite email addresses and encrypted raw invite
tokens. Those values are needed only until delivery has completed or the invite
is no longer allowed to be delivered.

After an erasure request is approved, subject-linked outbox payloads must be
scrubbed before the workflow can be considered complete.

## Matching rules

The provider can match subject-linked rows by:

- invite id snapshots via `aggregate_id`;
- subject email snapshots via `payload_json.email`.

The snapshot parameters matter because the wider erasure workflow can run user
and invite anonymisation before outbox scrubbing. Once those earlier providers
run, the original subject email and invite email may no longer be available from
current database rows.

## Mutation rules

For matched rows, the provider:

- keeps safe reference fields such as `invite_id`, `organisation_id`, `purpose`
  and `role`;
- removes delivery-only or unsafe payload values, including email, encrypted raw
  token and unknown future keys;
- adds scrub markers to `payload_json`;
- terminalises pending or processing rows as failed with the safe reason code
  `privacy_erasure_scrubbed`;
- clears unsafe historical `last_error` values on already-terminal rows.

The provider preserves row ids, aggregate references, event type and timestamps
so audit and operational history remain structurally intact.

## Out of scope

This slice does not implement:

- audit minimisation;
- DSR orchestration;
- platform API endpoints;
- worker execution;
- retention/purge runners.

The next slice should start controlled audit minimisation or add a small
orchestration layer that runs the already implemented user, invite and outbox
providers in a safe transaction.
