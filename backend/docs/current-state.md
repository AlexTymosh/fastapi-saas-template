# Current State

## Last Updated

2026-07-01

## Project Phase

Active development. The repository provides a backend-only FastAPI SaaS template
foundation and is not production-ready.

## Implemented

The following foundations are present in code and current documentation and
should still be verified against code before extension:

- FastAPI app factory and lifespan.
- Central master router.
- Health endpoints.
- SQLAlchemy async foundation.
- Alembic migrations foundation.
- Keycloak JWT validation hardened for OAuth2 Resource Server access tokens,
  including strict issuer/audience/`azp`/`iat`/`kid`/lifetime checks, startup
  OIDC metadata validation and JWKS forced refresh cooldown/singleflight
  protection.
- Local user projection with `external_auth_id`.
- Organisations, memberships and invites foundation.
- SMTP invite delivery provider with protected-environment NoOp guardrails when
  invite delivery is enabled.
- Platform staff, permissions, current platform identity endpoint foundation,
  platform list filters, limited platform user/organisation/audit views and
  OpenAPI operation ID hardening.
- Audit events foundation, including a backend-redacted limited platform audit
  view.
- Privacy governance foundation: processing purpose registry, lawful-basis and
  special-category condition primitives, per-subject processing authorisations,
  consent records, privacy notice acceptance records, service-layer processing
  checks, consent withdrawal and compliance audit events.
- Data Subject Request workflow foundation:
  - DSR persistence model, repository, service lifecycle and APIs;
  - idempotent submission controls;
  - execution state separated from administrative review status;
  - self-service submission for all modelled request types;
  - optional requester details captured for platform DSR review;
  - authorised representative DSR intake metadata with approval blocked until
    authority verification is implemented and completed;
  - approval restricted to request types with concrete execution policies;
  - cross-table subject export providers;
  - PostgreSQL provider integration coverage for outbox JSON predicates used by
    subject export, erasure impact preview and outbox erasure scrubbing;
  - streaming JSON ZIP archive generation for export artifacts;
  - export artifact worker flow and ops integration;
  - local and S3-compatible export artifact storage;
  - opt-in MinIO/Testcontainers coverage for S3-compatible export storage;
  - dedicated export artifact download URL and delivery confirmation rate
    limits;
  - platform erasure execution API;
  - executable erasure providers for audit, outbox, invites, platform staff,
    export-artifact metadata, privacy-governance minimisation, DSR workflow
    metadata and user profile;
  - explicit retain/manual-review policy entries for membership, organisation
    and consent records where automatic mutation would break tenant,
    access-control or compliance integrity;
  - provider decision preservation in erasure orchestration results;
  - audit minimisation before destructive erasure;
  - self-erasure execution rejection;
  - automatic fulfilment after successful approved erase execution;
  - export artifact retention runner with Taskfile ops commands;
  - erasure coverage contract tests that keep inventory, runtime coverage and
    impact preview aligned.
- Outbox foundation.
- Redis/rate limiting foundation, including route-level dependency policies,
  settings-aware policy resolution, authenticated reads, tenant flows, invite
  anti-abuse flows, platform read/audit reads, privacy export download URL
  limits and fail-closed platform write policies.
- Observability/OpenTelemetry foundation.
- pytest/Testcontainers foundation.
- `uv` dependency workflow:
  - `.python-version` pins Python 3.12;
  - `backend/pyproject.toml` uses `[dependency-groups].dev`;
  - `backend/uv.lock` is the only dependency lock source;
  - `Taskfile.yml` wraps common `uv run` checks;
  - `.pre-commit-config.yaml` uses local `uv` hooks;
  - GitHub Actions CI runs the backend quality gate with `uv`;
  - Docker backend image installs runtime dependencies from `uv.lock` and
    runs the backend process as an unprivileged application user.

## Partially Implemented

- Production hardening beyond the current non-root backend image and
  documented runtime secret handling baseline.
- Platform workflows beyond the current platform staff/user/organisation/audit
  and privacy DSR scope.
- Additional invite delivery providers and product-specific invite email
  template customisation beyond the current SMTP sink.
- Observability integration beyond the current foundation.
- Full BOLA/BFLA security test matrix outside the currently covered tenant BOLA,
  platform permission-matrix and feature-specific privacy permission tests.
- DSR hardening items that are intentionally separate from the current #328
  backend closure scope:
  - explicit delivery evidence semantics; done for URL issuance vs user or
    platform delivery confirmation, but future storage-native evidence can
    still extend it;
  - representative verification endpoints, evidence review and execution
    semantics beyond the current intake guardrails;
  - frontend/UI;
  - concrete execution pipelines for access, rectify, restrict, object and
    portability request types. These review-only types are blocked from approval
    by the central DSR service transition policy until execution policies exist.

## Not Implemented / Planned

The following areas should not be presented as complete without code
verification:

- Production-grade deployment hardening.
- Complete platform operations workflows beyond current backend slices.
- Full BOLA/BFLA security test matrix for every endpoint.
- Prometheus/Grafana stack or `/metrics` endpoint, unless added later.
- Frontend application.

## Known Risks

- Documentation may lag code.
- Documentation must not claim planned features as implemented.
- Very large DSR exports still need deployment-level writable temporary storage
  capacity planning even though archive generation now streams through a
  temporary file instead of materialising the ZIP in memory.
- Soft-deleted organisations are operational/audit records: platform admin
  workflows may request explicit visibility for support, compliance, audit or
  recovery, but tenant APIs must not accidentally expose them.
- Production Docker/runtime hardening now has a non-root backend image and
  runtime secret handling baseline, but deployment-specific controls such as
  read-only filesystems and capability drops still belong in deployment
  manifests.
- CORS policy is implemented as an explicit environment-driven allowlist and is
  disabled by default.
- CI should remain required and green before merging protected branches.
- Access-control tests need continuous expansion.
- Deleted or renamed docs must not leave broken links.

## Documentation Status

- `backend/docs/architecture.md` is the canonical architecture document.
- `backend/docs/rate-limiting.md` is the canonical rate-limiting document.
- `backend/docs/keycloak-identity-contract.md` contains the detailed identity
  contract.
- `backend/docs/observability.md` contains observability details.
- `backend/docs/testing-e2e.md` contains integration/e2e testing conventions.
- `backend/docs/access-control/en` is the canonical access-control
  documentation source.
- `backend/docs/privacy-dsr.md` contains the current DSR workflow summary.
- `backend/docs/privacy-export-artifacts.md` contains export artifact storage,
  worker, download URL, delivery confirmation and retention operations details.
- `backend/docs/privacy-dsr-328-closure-checklist.md` tracks closure readiness
  and final verification for issue #328.
- `backend/docs/privacy-dsr-export-providers.md` records the historical export
  provider slice and PostgreSQL provider integration coverage.
- `backend/docs/runtime-hardening.md` documents runtime secret handling and
  backend container hardening guidance.
- `SESSION_NOTES.md` contains short live handoff notes for AI-agent sessions.
- `README.md`, `AGENTS.md`, and `Taskfile.yml` are the primary developer
  workflow entry points.

## Testing Status

For local development, install dependencies through `uv`:

```bash
cd backend
uv sync --group dev
```

Preferred checks from the repository root:

```bash
task lint
task test:safe
task test:security
task test:contracts
task ci
```
