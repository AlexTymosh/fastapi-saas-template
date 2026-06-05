# DSR audit minimisation provider

This slice adds the first DSR-specific audit minimisation provider:

```text
audit.minimise_subject_actor_or_target_identifiers
```

The provider is intentionally not wired into the core erasure orchestrator yet.
It should be reviewed independently before automatic execution is enabled.

## Why audit is different

Audit rows should not be blindly deleted. They preserve operational and
compliance evidence, so the safer erasure behaviour is integrity-preserving
minimisation.

The provider keeps audit rows in place and removes direct subject-linked
identifiers and free-form context.

## Current scope

This first slice covers direct subject links:

- `audit_events.actor_user_id == subject_user_id`;
- `audit_events.target_type == "user" and target_id == subject_user_id`;
- `audit_events.target_type == "privacy_consent" and target_id == subject_user_id`;
- `audit_events.target_type == "privacy_notice" and target_id == subject_user_id`.

For matched rows, it minimises:

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

This avoids partial minimisation and leaves the future orchestration layer free
to mark the DSR execution as failed or manual-review-required.

## Out of scope

This slice does not implement:

- invite target joins;
- membership target joins;
- Data Subject Request target joins;
- export artifact target joins;
- platform staff target joins;
- orchestration wiring;
- API or worker execution;
- retention/purge scheduling.

Those linked-target joins should be added in a separate slice, preferably with
snapshot inputs from the core erasure orchestrator.
