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

- Admin Console: `http://localhost:8080/admin`
- Admin user: `admin`
- Admin password: `admin`
- Realm: `fastapi-saas`
- OIDC client used by backend JWT validation: `fastapi-backend`
- Dev test user for browser login in Keycloak: `api-user` / `api-user-password`

The imported dev client is intentionally configured for **Authorization Code + PKCE**:

- `standardFlowEnabled=true`
- `directAccessGrantsEnabled=false`
- explicit localhost redirect URIs (no wildcard)
- explicit localhost web origins (no wildcard)

> [!IMPORTANT]
> The previous password-grant (`grant_type=password`) testing path was intentionally removed.
> This repository no longer documents or enables Direct Access Grants for local development.

Registered local redirect URIs are limited to common localhost callback patterns used by browser apps and OAuth debugging helpers:

- `http://localhost:3000/auth/callback`
- `http://127.0.0.1:3000/auth/callback`
- `http://localhost:5173/auth/callback`
- `http://127.0.0.1:5173/auth/callback`
- `http://localhost:8787/callback`
- `http://127.0.0.1:8787/callback`

Ports `3000` and `5173` cover common local frontend dev servers, and `8787` is included for local OAuth callback helper tools.

Auth defaults are safe in this repository (`AUTH__ENABLED=false` in `.env.example`).  
To test real JWT validation locally, set:

```env
AUTH__ENABLED=true
AUTH__ISSUER_URL=http://localhost:8080/realms/fastapi-saas
AUTH__AUDIENCE=fastapi-backend
AUTH__CLIENT_ID=fastapi-backend
AUTH__ALGORITHMS=RS256
```

`AUTH__ALGORITHMS` intentionally supports only `RS256`.

> [!NOTE]
> Inside Docker Compose, the app container uses `AUTH__ISSUER_URL=http://keycloak:8080/realms/fastapi-saas` (`compose.yaml`).
> From the host machine, use `http://localhost:8080/realms/fastapi-saas`.

Manual local testing flow (without adding a frontend to this repo):

1. Use a browser-based OAuth/OIDC client tool that supports Authorization Code + PKCE.
2. Configure it with:
   - issuer: `http://localhost:8080/realms/fastapi-saas`
   - client_id: `fastapi-backend`
   - authorization endpoint and token endpoint from realm discovery
   - one of the registered localhost callback URIs above
3. Sign in through the browser (for local dev, you can use `api-user`).
4. Copy the resulting bearer `access_token`.
5. Call protected API endpoints with that token.

Example API call:

```bash
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"
```


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
| Keycloak  | http://localhost:8080     |

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
