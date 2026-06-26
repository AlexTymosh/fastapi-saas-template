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

# DSR audit minimisation provider

## Historical context

This slice introduced the first DSR-specific audit minimisation provider:

```text
audit.minimise_subject_actor_or_target_identifiers
```

At the time of this slice, the provider was reviewed independently before being
added to the broader erasure workflow. The current implementation has since
wired audit minimisation into the inventory-aligned erasure orchestration.

## Why audit is different

Audit rows should not be blindly deleted. They preserve operational and
compliance evidence, so the safer erasure behaviour is integrity-preserving
minimisation.

The provider keeps audit rows in place and removes direct subject-linked
identifiers and free-form context.

## Original direct-link scope

The first slice covered direct subject links:

- `audit_events.actor_user_id == subject_user_id`;
- `audit_events.target_type == "user" and target_id == subject_user_id`;
- `audit_events.target_type == "privacy_consent" and target_id == subject_user_id`;
- `audit_events.target_type == "privacy_notice" and target_id == subject_user_id`.

For matched rows, it minimised:

- `actor_user_id` when the subject is the actor;
- `target_id` when the subject is a direct target;
- `reason`;
- `metadata_json`;
- `ip_address`;
- `user_agent`.

The provider does not change `category`, `action`, `target_type`, `created_at`,
or `legal_hold_until`.

## Legal hold behaviour

If any matched audit row has an active `legal_hold_until`, the provider raises
`audit_erasure_legal_hold_active` before applying any mutation.

This avoids partial minimisation and lets the erasure execution boundary mark the
DSR execution as failed or manual-review-required.

## Superseded scope note

Later slices added linked-target discovery and orchestrator wiring for audit
minimisation. Use the current DSR documentation and closure checklist to evaluate
#328 readiness, not this historical slice note.
