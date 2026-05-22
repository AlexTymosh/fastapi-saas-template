# Configuration and local Compose boundaries

## Status

This project is in active development and is not production-ready.

This document defines how local configuration, Docker Compose, Vault, and deployment-time secrets are separated.

## Principles

- Environment variables are granular configuration values.
- `APP__ENVIRONMENT` is a validation and safety mode, not a hidden config selector.
- `.env.example` is a local development template, not a production secret store.
- `compose.yaml` is a local development stack, not a production deployment manifest.
- Vault in Docker Compose is an optional local dev/demo integration profile.
- Staging and production secrets must be provided by the deployment platform, Vault, or another secret manager.

## Application environment

Supported environment values should be treated as validation modes:

- `local`
- `test`
- `staging`
- `prod`

Do not use `APP__ENVIRONMENT` to silently load a bundled set of database, Redis, Keycloak, CORS, Vault, or rate-limit settings.

Prefer explicit values:

```env
APP__ENVIRONMENT=local
DATABASE__URL=postgresql+psycopg://app:app@localhost:5432/app
REDIS__URL=
VAULT__ENABLED=false
AUTH__ENABLED=false
RATE_LIMITING__ENABLED=false
```

## Local `.env`

`.env.example` is committed as a documented local template. Developers copy it to `.env` for local work:

```bash
cp .env.example .env
```

`.env` must not be committed.

The example values are intentionally weak local placeholders. They must not be reused in staging or production.

## Docker Compose local service credentials

`compose.yaml` reads local service credentials from granular variables:

```env
POSTGRES_DB=app
POSTGRES_USER=app
POSTGRES_PASSWORD=app

KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=admin

VAULT_DEV_ROOT_TOKEN_ID=dev-only-root-token
```

The application containers derive their container-internal database URL from `POSTGRES_*`:

```yaml
DATABASE__URL: postgresql+psycopg://${POSTGRES_USER:-app}:${POSTGRES_PASSWORD:-app}@postgres:5432/${POSTGRES_DB:-app}
```

This keeps the container URL tied to the Compose service hostname `postgres` while host-local development can use `DATABASE__URL` with `localhost`.

If a local password contains URL-reserved characters, URL-encode it before using it in a URL. For production, prefer a platform-provided full `DATABASE__URL` or secret manager integration.

## Docker Compose profiles

The default local stack should stay small and predictable.

Default services:

- `app`
- `worker`
- `outbox-dispatcher`
- `postgres`
- `redis`
- `keycloak`

Optional profiles:

- `tools` — one-shot utility services such as `migrate`
- `vault` — local Vault dev/demo service and init container
- `observability` — local OpenTelemetry Collector

Examples:

```bash
docker compose run --rm migrate
docker compose --profile vault up -d vault vault-init
docker compose --profile observability up -d otel-collector
```

## Vault boundary

Vault is disabled by default for local development:

```env
VAULT__ENABLED=false
VAULT__TOKEN=
```

The Compose Vault service uses Vault dev mode and is only for local development or integration experiments. It is not a production secret store.

Do not use `VAULT_DEV_ROOT_TOKEN_ID` in staging or production.

For staging and production, provide real Vault configuration through the deployment platform:

```env
VAULT__ENABLED=true
VAULT__ADDR=https://vault.example.com
VAULT__TOKEN=<provided-by-secret-manager>
VAULT__FAIL_FAST=true
```

Exact production authentication strategy can later be replaced with AppRole, Kubernetes auth, cloud IAM auth, or another supported Vault auth method.

## Processor governance

`PROCESSOR_GOVERNANCE__ENABLED` is an optional staging/prod deployment guardrail. When it is enabled, startup validation checks configured external processors and requires governance metadata for each active processor.

The current required processor keys are derived from actual runtime settings:

- `keycloak` when `AUTH__ENABLED=true`;
- `redis` whenever `REDIS__URL` is set, regardless of whether app rate limiting or edge-enforced rate limiting is used;
- `vault` when `VAULT__ENABLED=true`;
- `otlp` when `OBSERVABILITY__METRICS_ENABLED=true` and `OBSERVABILITY__EXPORTER=otlp`.

This rule is deliberate. Redis can be used outside the rate limiter path, for example as a task broker or health-checked infrastructure dependency. Do not couple Redis processor governance to `RATE_LIMITING__ENABLED`.

Minimum metadata per configured processor:

```env
PROCESSOR_GOVERNANCE__ENABLED=true
PROCESSOR_GOVERNANCE__REQUIRED=true
PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION=uk

PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__PURPOSE=cache_rate_limit_storage_and_async_task_broker
PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__DATA_CATEGORIES=rate_limit_identifiers,healthcheck_metadata
PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__REGION=uk
PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__COUNTRY=GB
PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__DPA_SIGNED=true
PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__RESTRICTED_TRANSFER=false
PROCESSOR_GOVERNANCE__PROCESSORS__REDIS__TRANSFER_MECHANISM=not_restricted
```

For restricted transfers, `TRANSFER_MECHANISM` must be one of the approved mechanisms implemented in settings validation: `adequacy`, `uk_idta`, `uk_addendum`, `bcr`, or `derogation`.

This is not a complete data-protection impact assessment, DPA registry, or clinical cross-border transfer policy. It is a startup guardrail that prevents obvious undocumented processor use while the broader GDPR/privacy module is still planned.

## Database migrations

Local Docker Compose migrations are explicit:

```bash
docker compose run --rm migrate
```

The application container must not run migrations automatically on every startup.

For staging and production, run migrations as a separate deployment/release step using the same application image and the real deployment `DATABASE__URL`:

```bash
python -m alembic upgrade head
```

Recommended rule:

```text
CI verifies code and migrations.
CD/deployment applies migrations before replacing or starting application containers.
```

## Production and staging

Do not use local Compose defaults in staging or production.

Production/staging should provide:

- `APP__ENVIRONMENT=staging` or `APP__ENVIRONMENT=prod`
- real `DATABASE__URL`
- real `REDIS__URL`
- real authentication settings
- real rate-limit secret or edge-enforced rate limiting
- real secret provider configuration if Vault is enabled
- processor governance metadata when `PROCESSOR_GOVERNANCE__ENABLED=true`

Production validation should reject known local/dev placeholders such as:

- `POSTGRES_PASSWORD=app`
- `KEYCLOAK_ADMIN_PASSWORD=admin`
- `VAULT_DEV_ROOT_TOKEN_ID=dev-only-root-token`
- `VAULT__TOKEN=dev-only-root-token`

## What not to do

Do not:

- use `APP__ENVIRONMENT` as a hidden config bundle selector;
- rely on runtime auto-detection to decide local/staging/prod;
- commit `.env`;
- use Docker Compose local defaults in staging or production;
- run migrations implicitly inside every app container startup;
- treat Vault dev mode as production-ready;
- treat `PROCESSOR_GOVERNANCE__ENABLED=false` as evidence that processors are governed.
