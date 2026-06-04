# DSR invite erasure provider

This slice adds the second controlled mutation provider for issue #328:

- `invites.anonymise_or_purge_subject_references`

The provider is intentionally narrow. It is not wired into public API endpoints,
background workers or automatic DSR execution yet.

## Behaviour

For an approved `erase` Data Subject Request, the provider locks invite rows that
match either of these subject links:

- the invite email matches the normalised subject email;
- `invites.revoked_by_user_id` matches the subject user id.

Invitee-side rows are kept in place and anonymised with deterministic tombstones
because the current schema keeps `email` and `token_hash` non-null and other
parts of the system may still reference the invite id.

For pending invitee-side rows, the provider also revokes the invite and clears
`expires_at`, making the invite unusable without deleting the row.

Revoker-only rows keep the invitee email/token intact and only clear the
subject-side `revoked_by_user_id` reference.

## Safety rules

The provider rejects:

- non-`erase` DSRs;
- non-approved DSRs;
- subjectless DSRs;
- DSRs whose subject user no longer exists.

The provider does not commit the transaction. Future orchestration should call it
inside an explicit transaction and record DSR execution/audit events separately.

## Why this is separate from user profile erasure

Invite erasure needs the subject email to locate invitee-side records. Once the
user profile has been anonymised, `users.email` may already be `NULL`.

To avoid ordering bugs in the future orchestration layer, the provider accepts an
optional `subject_email` snapshot. The orchestrator can capture the subject email
before running `users.anonymise_profile` and pass it to this provider.

## Out of scope

This slice does not implement:

- outbox payload scrubbing;
- audit minimisation;
- retention purge runners;
- DSR execution-state transitions;
- platform API endpoints.
