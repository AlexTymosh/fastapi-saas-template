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

# DSR invite erasure provider

## Historical context

This document described the controlled mutation provider for:

- `invites.anonymise_or_purge_subject_references`

The provider has since been included in the current erasure orchestration flow.

## Current status

Invite erasure/minimisation is part of the inventory-aligned erasure workflow
described in `backend/docs/privacy-dsr.md`.

## Behaviour

For an approved `erase` DSR, the provider handles invite rows linked to the
subject through:

- invitee email matching the normalised subject email snapshot;
- `invites.revoked_by_user_id` matching the subject user id.

Invitee-side rows are preserved and anonymised with deterministic tombstones
where schema constraints or operational references require the invite row to
remain.

Pending invitee-side rows are revoked and made unusable.

Revoker-only rows keep invitee-side data intact and clear only the subject-side
revoker reference.

## Ordering rule

Invite minimisation must run before user-profile anonymisation can remove the
subject email. The orchestrator should therefore capture a subject email
snapshot before direct identifiers are removed.
