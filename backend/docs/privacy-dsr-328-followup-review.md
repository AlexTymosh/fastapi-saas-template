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

# Issue #328 follow-up review

## Historical context

This review captured the project state after PR #405, before the final
inventory-aligned erasure coverage, provider decision preservation, platform
execution API, export retention, and documentation reconciliation work were
completed.

The findings in this file are retained only as historical implementation
context. They must not be used to decide whether #328 can be closed.

## Superseded findings

The earlier review identified missing runtime/policy coverage for several
privacy inventory areas. That status has been superseded.

Current documentation now records that the backend DSR scope includes:

- DSR persistence, repository, service lifecycle, and user/platform APIs;
- export artifacts, local development storage, S3-compatible storage, worker
  operations, download URL generation, and retention;
- cross-table subject export providers for the current privacy inventory;
- inventory-aligned erasure orchestration;
- provider decisions for executable, retained-by-policy, and manual-review
  records;
- platform erase execution and automatic fulfilment after successful execution;
- contract tests for inventory, export providers, erasure coverage, provider
  decisions, platform permissions, and privacy documentation.

## Current closure rule

Use `backend/docs/privacy-dsr-328-closure-checklist.md` as the closure checklist.

The current backend #328 scope may be closed when:

1. the documentation reconciliation is merged;
2. `task ci` passes;
3. any remaining non-blocking hardening work is tracked as separate follow-up
   issues.

## Remaining follow-up categories

The following categories are not #328 closure blockers:

- streaming archive generation for very large exports;
- PostgreSQL-specific export-provider integration coverage;
- explicit export delivery evidence semantics;
- authorised representative workflows;
- frontend/UI;
- execution pipelines for rectify/restrict/object/access/portability request
  types.
