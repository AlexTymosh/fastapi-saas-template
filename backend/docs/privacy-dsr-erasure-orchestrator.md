# DSR core erasure orchestrator

This document describes the internal orchestration contract for the inventory-
aligned erasure providers and explicit policy steps.

The orchestrator now covers:

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

The orchestrator is intentionally not exposed through public API or a worker yet.
It does not commit the transaction and does not fulfil the Data Subject Request.

## Why this exists

The individual providers are safe in isolation, but they must be run in a fixed
order.

The workflow needs a pre-erasure snapshot before direct identifiers are removed:

- subject email;
- subject-linked invite ids.

Those values are needed by the outbox and invite providers. If user or invite
anonymisation ran first without passing snapshots, later providers could lose the
ability to find subject-linked rows.

## Execution order

The order is:

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

Audit and outbox run early because they may contain direct subject identifiers,
delivery-only personal data and encrypted invite token material. Outbox still
blocks execution when subject-linked rows are currently `processing`, because the
worker may already have decrypted delivery material.

Invites run before the user profile because invite email and token material
should be minimised before the local user projection loses its original email.

Membership and organisation steps are policy coverage entries, not destructive
mutations. They preserve tenant relationship integrity while making the policy
explicit in provider results and contract tests.

Platform staff, export artifact metadata and privacy-governance source fields are
minimised before user-profile anonymisation where nullable. Compliance evidence
fields remain retained.

The user profile runs near the end because it removes direct subject identifiers
from the local account projection. DSR workflow metadata is minimised last so the
execution result and audit event can snapshot the subject id before request links
are cleared.

## Snapshot locking

The orchestrator locks and refreshes the subject user row before deriving the
snapshot. This prevents stale identity-map data from being used when a concurrent
profile refresh updates the local user email shortly before erasure execution.

The lock query uses `with_for_update()` and `populate_existing=True`, matching
the same stale-row guard used for DSR and outbox locking.

## Transaction behaviour

The orchestrator uses a nested transaction around provider mutations.

If a provider fails, provider mutations are rolled back and the DSR execution
status is marked as `failed` with a safe reason code. The caller still controls
the outer transaction boundary.

Provider/runtime failures during execution are returned as a failed
orchestration result so the caller's normal outer transaction can commit the DSR
failed state. Validation errors before execution starts still raise an error.

On success, the DSR execution status is marked as `ready`.

## Out of scope

This slice does not implement:

- platform API endpoints;
- background worker execution;
- fulfilment of `erase` requests;
- retention/purge runners;
- worker lock/dispatch coordination beyond blocking in-flight processing rows.

The next slice should perform the final #328 closure review after the runtime
coverage and contract tests pass broad CI.
