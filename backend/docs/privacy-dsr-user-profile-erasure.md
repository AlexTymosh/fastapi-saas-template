# DSR user profile erasure provider

This slice adds the first controlled mutation provider for issue #328:

- `users.anonymise_profile`

The provider anonymises only the subject's local `users` row for an approved
`erase` Data Subject Request. It does not commit the transaction and does not
change DSR lifecycle fields. Wider orchestration, audit recording and execution
state updates remain separate follow-up work.

## Mutated fields

The provider removes or resets direct user-profile identifiers:

- `external_auth_id` is replaced with a deterministic erased placeholder based
  on the retained local user id;
- `email` is set to `NULL`;
- `email_verified` is set to `false`;
- `first_name` and `last_name` are set to `NULL`;
- `onboarding_completed` is set to `false`;
- `suspended_reason` is set to `NULL` because it may contain free-text personal
  data.

The provider deliberately keeps the local user primary key so existing foreign
keys, audit references, DSR records, memberships and export artifacts remain
referentially intact.

## Safety rules

The provider rejects:

- non-`erase` DSRs;
- non-approved DSRs;
- DSRs without `subject_user_id`;
- DSRs whose subject user no longer exists.

The provider is idempotent. Running it again for the same already anonymised
profile returns `already_anonymised` with `affected_rows = 0`.

## Out of scope

This slice does not mutate:

- invites;
- outbox payloads;
- memberships;
- organisations;
- audit events;
- privacy-governance records;
- export artifacts;
- DSR status or execution state.

Next implementation slices should add invite/outbox mutation providers, then a
separate orchestration layer that executes providers inside one audited erasure
workflow.
