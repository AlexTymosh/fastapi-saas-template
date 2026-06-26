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

# DSR user profile erasure provider

## Historical context

This document described the first controlled mutation provider for issue #328:

- `users.anonymise_profile`

At the time of that slice, orchestration, execution audit recording, and
lifecycle updates were intentionally handled later. The current implementation
has since added those pieces.

## Current status

User-profile anonymisation is part of the inventory-aligned erasure workflow
described in `backend/docs/privacy-dsr.md`.

The provider remains responsible for removing or resetting direct local user
profile identifiers while preserving the local user primary key for referential
integrity.

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

## Safety rules

The provider must remain:

- limited to approved `erase` DSRs;
- subject-user scoped;
- idempotent;
- referentially safe for memberships, audit references, DSR records, and export
  artifacts.
