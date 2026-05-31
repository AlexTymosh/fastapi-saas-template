# Issue #328 follow-up review

## Current status

The current `main` branch contains a solid foundation for issue #328:

- Data Subject Request persistence and lifecycle foundation.
- User and platform DSR APIs.
- Export artifact model, local storage adapter, worker command, and signed local download URLs.
- Data inventory and provider registry contract.
- A fulfilment guard that prevents export DSRs from being fulfilled without a ready non-expired export artifact.
- Column-level inventory declarations.

The architecture is moving in the right direction, but issue #328 is not fully closed yet. The project still needs real cross-table export providers, erasure/anonymisation providers, production export storage, object retention cleanup, and an execution state model that is more explicit than `approved -> fulfilled`.

## 328-1 review

The 328-1 provider/inventory contract is mostly complete. It includes:

- table-level inventory coverage;
- explicit out-of-scope table declarations;
- provider keys derived from the inventory;
- model reference validation;
- core issue #328 table coverage checks;
- column-level field declarations.

Remaining quality gap found during review:

| Finding | Priority | Required action |
|---|---:|---|
| Inventory tests do not independently prove that every declared `PrivacyFieldInventory.name` exists as a SQLAlchemy table column. | P1 | Add a contract test that imports each declared model and verifies each declared inventory field against `model.__table__.c.keys()`. |
| Subject-link and high-risk field coverage is not guarded by a focused regression test. | P1 | Add explicit contract tests for subject-link columns and high-risk field-name patterns such as email, token, payload, metadata, reason, IP address, user agent, and storage keys. |
| Provider registry is still metadata-only, not runtime-bound to provider implementations. | P2 | Keep this as a deliberate 328-2/328-3 follow-up. Do not bind runtime providers until export execution is implemented. |

The included test file addresses the first two P1 gaps without changing public API, database schema, runtime behaviour, or existing provider semantics.

## Next best step: 328-2

The next step should be `privacy/dsr-execution-state-machine`.

Recommended scope for that branch:

1. Introduce explicit execution states instead of relying on only DSR status:
   - `not_started`
   - `queued`
   - `processing`
   - `ready`
   - `failed`
   - `partially_fulfilled`
   - `delivered`
2. Keep administrative review status separate from execution state.
3. Prevent `fulfilled` unless the relevant execution pipeline has reached a terminal successful state.
4. For export DSRs, link fulfilment to a ready export artifact and delivery evidence.
5. For erase DSRs, keep fulfilment blocked until erasure/anonymisation jobs exist.
6. Add API response fields only if they are safe and useful for platform operators.
7. Add tests for invalid transitions, failed execution, expired artifacts, and successful fulfilment.

## Regression risks to check before implementing 328-2

| Area | Risk | Check |
|---|---|---|
| API compatibility | Existing clients may expect simple DSR statuses only. | Add fields without removing current status values unless a migration plan exists. |
| Database migrations | Enum/check constraint changes can break existing rows. | Use additive columns first; avoid destructive status changes in the first PR. |
| Export artifacts | Existing ready artifacts should remain downloadable after fulfilment. | Keep download eligibility independent from DSR `fulfilled`, or explicitly allow `approved` and `fulfilled`. |
| Worker logic | Worker may process artifacts whose DSR state changes while queued. | Re-check DSR eligibility at claim and generation time. |
| Tests | Existing lifecycle tests may assume direct `approved -> fulfilled`. | Update only through service-level fulfilment rules, not raw transition shortcuts. |

## Recommended decomposition

328-2 is large enough to split into at least two PRs:

1. `privacy/dsr-execution-state-foundation`
   - add execution state columns/model;
   - add repository/service methods;
   - add tests;
   - no worker behaviour change yet.
2. `privacy/dsr-export-execution-integration`
   - integrate export artifact worker with execution state;
   - block fulfilment on delivery evidence;
   - update API/contract tests.

Avoid implementing erasure in 328-2. Erasure should be a later branch after export execution is stable.
