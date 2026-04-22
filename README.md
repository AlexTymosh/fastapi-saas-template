# 🏗️ Project Under Development

This project is currently in the **active development** and architectural design phase.

---

## 🚀 Quick Start (Local Development)

### 1. Requirements

- Docker Desktop (with Docker Compose v2)
- Git

---

### 2. Clone repository

```bash
git clone https://github.com/AlexTymosh/fastapi-saas-template.git
cd fastapi-saas-template
```

---

### 3. Environment configuration

Create `.env` file in the project root (or copy from example):

```bash
cp .env.example .env
```

> [!NOTE]
> Secrets are loaded from Vault in development mode.  
> `.env` is used only for bootstrap configuration.

---

### 4. Run project

```bash
docker compose up --build -d
```

---

### 5. Apply database migrations (first run)

After the containers are up, apply Alembic migrations inside the `app` container:

```bash
docker compose exec app python -m alembic upgrade head
```

> [!NOTE]
> This step is required on the first run and after resetting volumes with `docker compose down -v`.

Optional check:

```bash
docker compose exec app python -m alembic check
```

---

### 6. Check application


### 6.1 Keycloak (local identity provider)

This repository is **backend-only**. Keycloak is the identity provider, while organisations/memberships/invites stay in the local business database.

Start all services (including Keycloak):

```bash
docker compose up --build -d
```

Local Keycloak defaults:

- Canonical issuer URL: `http://keycloak.local:8080/realms/fastapi-saas`
- Realm discovery URL: `http://keycloak.local:8080/realms/fastapi-saas/.well-known/openid-configuration`
- Admin Console: `http://keycloak.local:8080/admin`
- Admin user: `admin`
- Admin password: `admin`
- Realm: `fastapi-saas`
- Browser/public OIDC client for local Authorization Code + PKCE login: `fastapi-web`
- Backend JWT audience expected by FastAPI: `fastapi-api`
- Dev test user for browser login in Keycloak: `api-user` / `api-user-password`

The imported dev client is intentionally configured for **Authorization Code + PKCE**:

- `standardFlowEnabled=true`
- `directAccessGrantsEnabled=false`
- explicit localhost redirect URIs (no wildcard)
- explicit localhost web origins (no wildcard)

> [!IMPORTANT]
> The previous password-grant (`grant_type=password`) testing path was intentionally removed.
> This repository no longer documents or enables Direct Access Grants for local development.

To keep `iss` stable across browser and Docker Compose runtime, local development uses one explicit hostname: `keycloak.local`.

Add a hosts-file entry on your machine before running OAuth/OIDC flows:

- macOS/Linux (`/etc/hosts`): `127.0.0.1 keycloak.local`
- Windows (`C:\Windows\System32\drivers\etc\hosts`): `127.0.0.1 keycloak.local`

Docker Compose maps this same hostname to the Keycloak container on the internal network, so the backend and browser resolve the same issuer URL.

Registered local redirect URIs are limited to common localhost callback patterns used by browser apps and OAuth debugging helpers:

- `http://localhost:3000/auth/callback`
- `http://127.0.0.1:3000/auth/callback`
- `http://localhost:5173/auth/callback`
- `http://127.0.0.1:5173/auth/callback`
- `http://localhost:8787/callback`
- `http://127.0.0.1:8787/callback`

Ports `3000` and `5173` cover common local frontend dev servers, and `8787` is included for local OAuth callback helper tools.

Auth defaults are safe in this repository (`AUTH__ENABLED=false` in `.env.example`), and `compose.yaml` does not override this.  
To test real JWT validation locally, set:

```env
AUTH__ENABLED=true
AUTH__ISSUER_URL=http://keycloak.local:8080/realms/fastapi-saas
AUTH__AUDIENCE=fastapi-api
AUTH__CLIENT_ID=fastapi-web
AUTH__ALGORITHMS=RS256
```

`AUTH__ALGORITHMS` intentionally supports only `RS256`.
`AUTH__*` is the authoritative runtime JWT configuration block.
`SECURITY__KEYCLOAK_CLIENT_SECRET` remains optional for non-runtime confidential-client integrations.

### 6.2 Verifiable local auth scenario (Authorization Code + PKCE)

This repository does not include a frontend app. Use any browser-based OAuth/OIDC helper that supports Authorization Code + PKCE.

Runtime assumptions for this scenario:

- `AUTH__ENABLED=true` (backend auth boundary enabled)
- `AUTH__ISSUER_URL=http://keycloak.local:8080/realms/fastapi-saas` (same as token `iss`)
- `AUTH__AUDIENCE=fastapi-api` (FastAPI validates `aud` against this value)
- `AUTH__CLIENT_ID=fastapi-web` (FastAPI uses this for `resource_access.<client_id>.roles` extraction)
- backend started via Docker Compose (`compose.yaml`)

Steps:

1. Start the stack:
   ```bash
   docker compose up --build -d
   ```
2. Confirm hostname resolution on host:
   ```bash
   curl -fsS http://keycloak.local:8080/realms/fastapi-saas/.well-known/openid-configuration
   ```
3. In your OAuth/OIDC helper tool, configure:
   - issuer: `http://keycloak.local:8080/realms/fastapi-saas`
   - client_id: `fastapi-web`
   - redirect URI/callback: one of:
     - `http://localhost:8787/callback`
     - `http://localhost:3000/auth/callback`
     - `http://localhost:5173/auth/callback`
   - grant type: Authorization Code
   - PKCE method: `S256`
4. Sign in through Keycloak (for local dev, you can use `api-user` / `api-user-password`) and copy the resulting `access_token`.
5. Optional smoke check: confirm the token issuer is the canonical URL:
   ```bash
   python -c "import base64, json; t='<access_token>'.split('.')[1]; print(json.loads(base64.urlsafe_b64decode(t+'='*(-len(t)%4)))['iss'])"
   ```
6. Call the protected endpoint:
   ```bash
   curl http://localhost:8000/api/v1/users/me \
     -H "Authorization: Bearer <access_token>"
   ```
7. Expected result:
   - HTTP `200 OK`
   - token is accepted because `iss == http://keycloak.local:8080/realms/fastapi-saas`
   - local user projection is created/refreshed from JWT claims (`sub`-based linkage)

Troubleshooting:

- If you get issuer mismatch errors, re-check hosts mapping and confirm the token `iss` is `http://keycloak.local:8080/realms/fastapi-saas`.


Health endpoint:

```bash
curl http://localhost:8000/api/v1/health/live
```

Expected response:

```json
{"status":"ok"}
```

Readiness endpoint:

```bash
curl http://localhost:8000/api/v1/health/ready
```



---


## 🔬 Run integration tests (optional)

Before an important commit, you can run the integration test suite against real PostgreSQL and Redis services.

### 1. Start the services

```bash
docker compose up -d
```

### 2. Set test environment variables in PowerShell

```powershell
$env:TEST_DATABASE_URL="postgresql+psycopg://app:app@localhost:5432/app"
$env:TEST_REDIS_URL="redis://localhost:6379/0"
```

### 3. Run integration tests

```bash
pytest -q -m integration -rs
```

If you later run tests in the same terminal without integration variables, remove them first:

```powershell
Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:TEST_REDIS_URL -ErrorAction SilentlyContinue
```

---





### 7. Services

| Service   | URL / Host                |
|-----------|---------------------------|
| API       | http://localhost:8000     |
| Postgres  | postgres:5432 (internal)  |
| Redis     | redis:6379 (internal)     |
| Vault     | http://localhost:8200     |
| Keycloak  | http://keycloak.local:8080 |

Vault dev token:

```
dev-only-root-token
```

---

### 8. Vault (development)

Secrets are automatically initialized via `vault-init` container.

Example path:

```
secret/fastapi-saas-template
```

---

### 9. Stop project

```bash
docker compose down
```

Remove volumes (reset DB):

```bash
docker compose down -v
```

> [!IMPORTANT]
> After `docker compose down -v`, the database is recreated from scratch.  
> Run migrations again:
>
> ```bash
> docker compose up --build -d
> docker compose exec app python -m alembic upgrade head
> ```

---

## 📝 Documentation

For technical details, project goals, and the current roadmap:

👉 **[README.draft.md](./README.draft.md)**

---

> [!NOTE]
> Official guides and comprehensive documentation will be provided once the base setup is complete.


## 🔐 Current authentication scope

Implemented now:

- Keycloak is the identity source (JWT issuer and claims authority).
- FastAPI validates bearer JWTs (issuer, signature, `aud`, `exp`) with `RS256`.
- Backend maps token claims into `AuthenticatedPrincipal`.
- Backend keeps local JIT user projection using `external_auth_id == sub`.
- Organisations, memberships, and invites remain local business data in the app DB.

Intentionally out of scope in this repository:

- Local password login
- Local registration
- Local email verification/captcha
- Frontend login UI
- Production-ready frontend OIDC flow in this repository

Identity model split:

- Keycloak = identity source.
- FastAPI app DB = business model (organisations, memberships, invites, local user projection).

Development-only Keycloak note:

- `docker/keycloak/realm-export.json` is for local development only.
- Production OIDC clients must use strict deployment-specific redirect URIs and web origins (no wildcard settings).
