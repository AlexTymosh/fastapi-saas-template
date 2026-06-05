# DSR audit linked-target minimisation

This slice extends the DSR-specific audit minimisation provider.

The first audit minimisation slice handled only direct subject audit rows:

- `actor_user_id == subject_user_id`;
- direct subject targets such as `target_type='user'` and `target_id` matching
  the subject user id.

This slice adds linked target discovery for audit rows where the subject is
identified through another privacy-inventory table.

## Linked target types

The provider now snapshots linked target ids before mutating audit rows:

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

## Out of scope

This slice does not wire audit minimisation into the core erasure orchestrator.
That should happen in a later PR after this linked-target provider has passed
review.
