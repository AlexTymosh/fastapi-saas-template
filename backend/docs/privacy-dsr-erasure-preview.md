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

# DSR erasure preview

## Historical context

This document described the dry-run preview slice that was introduced before
concrete erasure providers were wired into the current runtime.

The preview layer remains useful as an operator-facing view of the provider set,
but this file is no longer the current implementation status document.

## Current status

The current erasure implementation is documented in:

- `backend/docs/privacy-dsr.md`;
- `backend/docs/privacy-dsr-erasure-orchestrator.md`;
- `backend/docs/privacy-dsr-erasure-execution.md`.

The current workflow includes database-backed providers, provider decisions,
platform execution, failed-state recording, audit evidence, and automatic
fulfilment after successful approved erasure.

## Preview contract

The preview should continue to expose request-scoped erasure impact without
mutating records.

It should remain aligned with:

- inventory-derived provider keys;
- provider execution order;
- retained-by-policy decisions;
- manual-review decisions;
- executable minimisation providers.
