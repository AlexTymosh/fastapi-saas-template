# DSR erasure and anonymisation plan

## Status

Issue #328 is not ready to close yet.

The project now has:

- DSR persistence and review APIs;
- DSR execution-state separation for export requests;
- cross-table subject export providers;
- production-capable S3-compatible export artifact storage.

The next architectural slice is erasure/anonymisation. This must not start as
ad-hoc SQL updates. It needs an implementation plan derived from the privacy
inventory so future personal-data tables cannot bypass the erasure workflow.

## This slice

This slice adds a code-level erasure-provider plan derived from
`PRIVACY_DATA_INVENTORY`.

It does not mutate data yet.

The goal is to make the next implementation branch safer by proving:

- every declared `erasure_provider_key` has a planned provider entry;
- provider keys are unique;
- each provider has a concrete execution mode;
- tables with `REVIEW_REQUIRED`, retained audit integrity, or legal-basis
  requirements are marked for manual review.

## Recommended implementation order

1. Add concrete erasure provider classes for user profile, invites and outbox.
2. Add dry-run planning output for platform reviewers.
3. Add execution records and idempotency for erasure jobs.
4. Add real mutations behind an explicit `confirmed` execution path.
5. Add audit events for planned, skipped, applied and failed erasure steps.
6. Add retention/purge runners after erasure execution is stable.

## Guardrails

Erasure providers must preserve referential integrity. Prefer anonymisation or
minimisation when rows are linked to audit, membership or tenant integrity.

Do not delete audit rows by default. Minimise actor/network identifiers only when
the policy allows it and keep structured event integrity.

Do not copy raw tokens, invite secrets, storage keys, processing tokens or
free-text failure details into erasure logs.

## Current provider modes

| Inventory strategy | Execution mode | Meaning |
|---|---|---|
| `anonymise_subject` | `anonymise` | Replace direct identifiers while keeping row integrity. |
| `delete_when_allowed` | `delete_when_allowed` | Delete or scrub rows only after retention/legal checks. |
| `retain_and_minimise` | `retain_and_minimise` | Keep relationship/history, minimise subject identifiers. |
| `retain_with_legal_basis` | `retain_with_legal_basis` | Retain by policy, expose manual-review result. |
| `not_applicable` | `not_applicable` | No automatic mutation. |

## Next branch

Recommended branch name:

```text
privacy/dsr-erasure-provider-contract
```

Then continue with:

```text
privacy/dsr-erasure-user-invite-outbox
```

Do not combine full erasure, retention purge and audit minimisation in one PR.
That would create high regression risk in memberships, invites, outbox delivery
and audit history.
