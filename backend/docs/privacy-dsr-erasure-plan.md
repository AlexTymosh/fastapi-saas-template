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

# DSR erasure and anonymisation plan

## Historical context

This document described the planning slice that preceded the concrete erasure
runtime. Its original purpose was to prevent ad-hoc SQL updates by deriving
provider work from the declared privacy inventory.

The implementation has since moved beyond this plan.

## Current status

The current DSR erasure workflow is documented in:

- `backend/docs/privacy-dsr.md`;
- `backend/docs/privacy-dsr-328-closure-checklist.md`;
- `backend/docs/privacy-dsr-erasure-orchestrator.md`.

The current implementation includes:

- inventory-aligned erasure provider keys;
- executable minimisation providers;
- explicit retained-by-policy and manual-review provider decisions;
- platform erase execution;
- execution audit evidence;
- automatic fulfilment after successful approved erase execution;
- retention handling for export artifacts.

## Planning decisions that remain valid

The following architectural rules from the original plan remain valid:

- erasure providers must preserve referential integrity;
- audit rows must not be deleted by default;
- personal identifiers should be minimised rather than destructively removed
  when rows preserve tenant, audit, or compliance integrity;
- raw tokens, storage keys, processing tokens, and unsafe free-text error details
  must not be copied into erasure logs;
- full erasure, retention, and audit minimisation work should stay decomposed
  into small, reviewable changes.
