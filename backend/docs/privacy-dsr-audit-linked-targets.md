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

# DSR audit linked-target minimisation

## Historical context

This slice extended the DSR-specific audit minimisation provider beyond direct
subject audit rows.

The first audit minimisation slice handled only direct subject audit rows:

- `actor_user_id == subject_user_id`;
- direct subject targets such as `target_type='user'` and `target_id` matching
  the subject user id.

This slice added linked target discovery for audit rows where the subject is
identified through another privacy-inventory table.

## Linked target types

The provider snapshots linked target ids before mutating audit rows:

- invites reached through the subject email or `invites.revoked_by_user_id`;
- memberships reached through `memberships.user_id`;
- data subject requests reached through requester, subject, or reviewer links;
- export artifacts reached through subject/requester/requested/generated links;
- platform staff rows reached through user or creator links.

Matching audit rows are retained, but minimised.

## Minimisation behaviour

For matched rows, the provider removes:

- `actor_user_id` when the subject is the actor;
- `target_id` when the target points to a direct or linked subject target;
- free-form `reason`;
- `metadata_json`;
- `ip_address`;
- `user_agent`.

Rows under active legal hold still block the provider before any mutation.

## Superseded scope note

The current implementation has since integrated audit linked-target
minimisation into the inventory-aligned erasure orchestration. Use the current
DSR documentation and closure checklist for #328 status.
