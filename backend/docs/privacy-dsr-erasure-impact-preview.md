# DSR erasure impact preview

This slice adds the first database-backed, non-destructive erasure preview for
approved `erase` Data Subject Requests.

The preview still does not update, delete or anonymise data. It only validates
that the DSR is eligible for erasure planning and estimates the number of rows
that the first concrete providers would touch.

## Scope

Currently scoped providers:

- `users.anonymise_profile`
- `invites.anonymise_or_purge_subject_references`
- `outbox.purge_or_scrub_payload`

All other inventory-derived erasure providers are returned as `not_scoped_yet`.
This keeps the preview honest: platform operators can see which parts of the
future erasure workflow have row-level impact estimation and which still need a
later implementation slice.

## Validation rules

`build_erasure_impact_preview()` rejects:

- non-`erase` DSRs;
- non-approved DSRs;
- DSRs without a subject user;
- DSRs whose subject user no longer exists.

These are failure cases by design. Destructive erasure execution must not start
from submitted, rejected, cancelled, fulfilled or subjectless requests.

## Counting rules

The first scoped preview counts:

- the subject `users` row;
- invite rows where the subject email matches the invite email or the subject is
  the revoker;
- outbox rows linked to those invite ids or carrying the subject email in the
  outbox JSON payload.

Outbox counts use distinct event ids so a row matched by both aggregate id and
payload email is counted once.

## Remaining work

Next implementation slice:

1. Add controlled mutation providers for user profile anonymisation.
2. Add controlled invite anonymisation or purge logic.
3. Add controlled outbox payload scrubbing.
4. Keep audit minimisation and retention purge as later branches.
