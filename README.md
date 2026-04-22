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

Canonical local issuer used everywhere in local development:

- `http://keycloak.local:8080/realms/fastapi-saas`

Local Keycloak defaults:

- Realm: `fastapi-saas`
- Admin Console: `http://keycloak.local:8080/admin`
- Admin user: `admin`
- Admin password: `admin`
- OIDC client used by backend JWT validation: `fastapi-backend`
- Dev test user for browser login in Keycloak: `api-user` / `api-user-password`

The imported dev client is intentionally configured for **Authorization Code + PKCE**:

- `standardFlowEnabled=true`
- `directAccessGrantsEnabled=false`
- explicit localhost redirect URIs (no wildcard)
- explicit localhost web origins (no wildcard)

> [!IMPORTANT]
> The password-grant (`grant_type=password`) path is intentionally removed for local development.
> This repository documents only Authorization Code + PKCE for user login testing.

#### Hostname requirement (one-time local setup)

`keycloak.local` must resolve on your machine so browser-based login and issuer checks use the same stable URL as the backend runtime.

Add this hosts-file entry:

```text
127.0.0.1 keycloak.local
```

- macOS/Linux: add it to `/etc/hosts`
- Windows: add it to `C:\Windows\System32\drivers\etc\hosts`

Docker Compose already gives the backend container the same hostname via the internal network alias (`keycloak.local`), so `AUTH__ISSUER_URL` is identical in host docs and container runtime.

Auth defaults are safe in this repository (`AUTH__ENABLED=false` in `.env.example`).  
To test real JWT validation locally, set:

```env
AUTH__ENABLED=true
AUTH__ISSUER_URL=http://keycloak.local:8080/realms/fastapi-saas
AUTH__AUDIENCE=fastapi-backend
AUTH__CLIENT_ID=fastapi-backend
AUTH__ALGORITHMS=RS256
```

`AUTH__ALGORITHMS` intentionally supports only `RS256`.

Registered local redirect URIs are limited to common localhost callback patterns used by browser apps and OAuth debugging helpers:

- `http://localhost:3000/auth/callback`
- `http://127.0.0.1:3000/auth/callback`
- `http://localhost:5173/auth/callback`
- `http://127.0.0.1:5173/auth/callback`
- `http://localhost:8787/callback`
- `http://127.0.0.1:8787/callback`

#### Verifiable local scenario (Authorization Code + PKCE)

1. Ensure the hosts entry exists and start the stack:

   ```bash
   docker compose up --build -d
   ```

2. Confirm issuer discovery is reachable at the canonical URL:

   ```bash
   curl http://keycloak.local:8080/realms/fastapi-saas/.well-known/openid-configuration
   ```

3. In a browser-based OAuth/OIDC client tool that supports Authorization Code + PKCE, configure:
   - issuer: `http://keycloak.local:8080/realms/fastapi-saas`
   - client ID: `fastapi-backend`
   - redirect URI: one allowed callback, for example `http://localhost:8787/callback`

4. Sign in as `api-user` and exchange the authorization code for an `access_token`.

5. (Optional smoke check) Verify token issuer:

   ```bash
   python -c "import base64,json; t='<access_token>'.split('.')[1]; print(json.loads(base64.urlsafe_b64decode(t + '='*(-len(t)%4)))['iss'])"
   ```

   Expected `iss`: `http://keycloak.local:8080/realms/fastapi-saas`.

6. Call the protected endpoint:

   ```bash
   curl http://localhost:8000/api/v1/users/me \
     -H "Authorization: Bearer <access_token>"
   ```

Expected outcome in this local Docker Compose runtime:

- backend accepts the token (issuer/audience/signature checks pass)
- `users` local projection is created or refreshed (`external_auth_id == sub`)
- API returns HTTP `200` from `GET /api/v1/users/me`


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
