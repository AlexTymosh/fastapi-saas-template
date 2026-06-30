# Runtime hardening

## Scope

This document records the current backend runtime hardening baseline for
application containers and deployment-time secrets.

The backend is still an active-development template. This document describes the
minimum runtime posture that should be preserved by future production deployment
work; it is not a complete production deployment manifest.

## Runtime secrets

Runtime secrets must be supplied by the deployment environment, Vault, or another
secret manager. They must not be committed to source control, copied into Docker
images, passed as Docker build arguments, or written into application logs.

Current secret-like settings include:

- `SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY`
- `SECURITY__KEYCLOAK_CLIENT_SECRET`
- `RATE_LIMITING__IDENTIFIER_SECRET`
- `RATE_LIMITING__EDGE_ASSERTION_SECRET`
- `AUDIT__NETWORK_IDENTIFIER_SECRET`
- `VAULT__TOKEN`
- `VAULT__ROLE_ID`
- `VAULT__SECRET_ID`
- `INVITE_DELIVERY__SMTP_PASSWORD`
- `PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET`
- `PRIVACY_EXPORTS__S3_ACCESS_KEY_ID`
- `PRIVACY_EXPORTS__S3_SECRET_ACCESS_KEY`

Operational rules:

- keep local `.env` files local-only;
- use deployment secret stores for staging and production;
- keep staging and production values distinct from local/test values;
- rotate any value that may have been copied into logs, screenshots, tickets, or
  issue comments;
- do not print `Settings.model_dump()` or equivalent full configuration dumps in
  runtime logs;
- prefer one secret per purpose, rather than reusing one value across auth, rate
  limits, audit, outbox encryption or export signing.

## No secrets in images

The backend Docker image must remain environment-agnostic.

Do not add `ARG` or `ENV` instructions for real deployment secrets in the
Dockerfile. Image build arguments and image layers are not a safe secret storage
boundary. The image should be built once and promoted between environments while
runtime configuration is supplied externally.

## Container runtime hardening

The backend Dockerfile runs the application as the non-root, unprivileged
`app:app` user.
Root is used only during image build for package installation and dependency
installation.

Production-like deployments should add runtime controls outside the Dockerfile:

- run with a read-only root filesystem where the platform supports it;
- mount only explicit writable paths that are required by the selected storage
  backend or process manager;
- avoid privileged containers;
- drop Linux capabilities by default and add back only those that are required;
- do not mount the Docker daemon socket into application containers;
- run migrations and one-off maintenance commands as separate release/admin
  processes using the same image and secret source as the API.

## Local development exception

The repository's local Compose profile bind-mounts `./backend:/app` to support
live reload and developer workflows. That local bind mount is not a production
runtime contract and should not be copied into staging or production manifests.
