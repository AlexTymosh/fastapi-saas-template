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

# DSR erasure impact preview

## Historical context

This slice added the first database-backed, non-destructive erasure preview for
approved `erase` Data Subject Requests.

The preview validated that a DSR was eligible for erasure planning and estimated
the number of rows that the first concrete providers would touch.

## Original scoped providers

The original preview covered:

- `users.anonymise_profile`;
- `invites.anonymise_or_purge_subject_references`;
- `outbox.purge_or_scrub_payload`.

At that point, the remaining inventory-derived erasure providers were surfaced as
not scoped for preview yet so platform operators could distinguish estimated row
impact from later implementation slices.

## Validation rules

`build_erasure_impact_preview()` rejected:

- non-`erase` DSRs;
- non-approved DSRs;
- DSRs without a subject user;
- DSRs whose subject user no longer existed.

These failure cases were deliberate. Destructive erasure execution must not start
from submitted, rejected, cancelled, fulfilled, or subjectless requests.

## Counting rules

The first scoped preview counted:

- the subject `users` row;
- invite rows where the normalised subject email matched the invite email or the
  subject was the revoker;
- outbox rows linked to those invite ids or carrying the normalised subject email
  in the outbox JSON payload.

Subject emails were trimmed and lowercased before comparisons. Outbox payload
emails were also trimmed and lowercased during matching. This kept the preview
aligned with invite creation while still supporting mixed-case IdP emails stored
on user profiles.

Outbox counts used distinct event ids so a row matched by both aggregate id and
payload email was counted once.

## Superseded scope note

The current implementation now has inventory-aligned erasure orchestration,
provider decisions, platform execution, and automatic fulfilment. Use the current
DSR documentation and closure checklist for #328 status.
