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
