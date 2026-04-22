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
- OIDC public client for local browser login testing: `fastapi-backend`
- Dev test user: `api-user` / `api-user-password`

The local client is intentionally configured for **Authorization Code + PKCE** (browser-based login):

- `standardFlowEnabled=true`
- `directAccessGrantsEnabled=false` (password grant intentionally disabled)
- explicit local development redirect URIs only:
  - `http://localhost:3000/callback`
  - `http://127.0.0.1:3000/callback`
  - `http://localhost:5173/callback`
  - `http://127.0.0.1:5173/callback`
- explicit local development web origins only:
  - `http://localhost:3000`
  - `http://127.0.0.1:3000`
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`

Ports `3000` and `5173` are included as common local dev ports for browser apps and OAuth/OIDC test tools.  
These settings are **local development only** and are intentionally not wildcard/open-ended.

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
When the API runs inside Docker Compose, it uses the internal issuer URL `http://keycloak:8080/realms/fastapi-saas` (see `compose.yaml`).
Use `http://localhost:8080/realms/fastapi-saas` only when running the backend process directly on the host.

This repository is backend-only and does **not** provide a login UI.  
For local manual testing of protected endpoints, obtain a Keycloak access token using an external browser-based OAuth/OIDC client that supports **Authorization Code + PKCE** and configure it with:

- Issuer/realm: `http://localhost:8080/realms/fastapi-saas`
- Client ID: `fastapi-backend`
- Redirect URI: one of the callback URIs listed above (for the tool you use)

Then copy the returned `access_token`.

Use the returned `access_token` for protected backend endpoints, for example:

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

- Local signup/password flows
- Local email verification/captcha
- Password reset flows
- Frontend login UI
- Production-ready frontend OIDC implementation in this repository

Important note:

- Previous local docs that used the password grant (`grant_type=password`) were intentionally removed.  
  The target direction is browser-based Authorization Code + PKCE.
- The backend auth boundary remains JWT bearer validation against Keycloak-issued tokens.
- The local Keycloak client settings in this repository are for development only; production clients must use strict deployment-specific redirect URIs and web origins.

Identity model split:

- Keycloak = identity source.
- FastAPI app DB = business model (organisations, memberships, invites, local user projection).
