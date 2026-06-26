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

# DSR core erasure orchestrator

## Current status

This document now describes the current internal orchestration contract for the
inventory-aligned erasure providers and explicit policy steps.

The orchestrator is called by the command/service boundary used by the platform
erasure execution API. The outer caller owns the application transaction and DSR
lifecycle transition.

## Provider coverage

The orchestrator covers:

1. `audit.minimise_subject_actor_or_target_identifiers`
2. `outbox.purge_or_scrub_payload`
3. `invites.anonymise_or_purge_subject_references`
4. `memberships.minimise_subject_link`
5. `organisations.review_subject_references`
6. `platform_staff.minimise_subject_or_creator_links`
7. `export_artifacts.delete_object_minimise_subject_or_actor_metadata`
8. `privacy_governance.minimise_authorizations`
9. `privacy_governance.minimise_consent_records`
10. `privacy_governance.minimise_notice_acceptances`
11. `users.anonymise_profile`
12. `dsr.minimise_workflow_identifiers`

## Why this exists

The individual providers are safe in isolation, but they must run in a fixed
order.

The workflow needs a pre-erasure snapshot before direct identifiers are removed:

- subject email;
- subject-linked invite ids;
- subject user id.

Those values are required by outbox, invite, audit, and workflow metadata
providers. Without snapshots, later providers could lose the ability to find
subject-linked rows.

## Execution order

```text
snapshot subject_email/invite_ids/subject_user_id
→ audit
→ outbox
→ invites
→ membership policy
→ organisation policy
→ platform staff minimisation
→ export artifact metadata minimisation
→ privacy governance minimisation/policy
→ users
→ DSR workflow metadata minimisation
```

## Transaction behaviour

The orchestrator uses a nested transaction around provider mutations.

If a provider fails, provider mutations are rolled back and the DSR execution
status is marked as failed with a safe reason code. The caller still controls the
outer transaction boundary.

On success, the DSR execution status is marked as ready. The service layer then
maps successful approved erase execution to DSR fulfilment.

## Provider decision contract

Provider results must preserve the policy decision, not just row counts.

Important decisions include:

- `minimised`;
- `already_minimised`;
- `retained_by_policy`;
- `manual_review_policy`.

This prevents retained/manual-review rows from being misread as unhandled simply
because they have `affected_rows = 0`.
