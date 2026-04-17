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
git clone https://github.com/<your-username>/fastapi-saas-template.git
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
docker compose up --build
```

---

### 5. Check application

Health endpoint:

```bash
curl http://localhost:8000/api/v1/health/live
```

Expected response:

```json
{"status":"ok"}
```

---

### 6. Services

| Service   | URL / Host                  |
|----------|----------------------------|
| API      | http://localhost:8000      |
| Postgres | postgres:5432 (internal)   |
| Redis    | redis:6379 (internal)      |
| Vault    | http://localhost:8200      |

Vault dev token:

```
dev-only-root-token
```

---

### 7. Vault (development)

Secrets are automatically initialized via `vault-init` container.

Example path:

```
secret/fastapi-saas-template
```

---

### 8. Stop project

```bash
docker compose down
```

Remove volumes (reset DB):

```bash
docker compose down -v
```

---

## 📝 Documentation

For technical details, project goals, and the current roadmap:

👉 **[README.draft.md](./README.draft.md)**

---

> [!NOTE]
> Official guides and comprehensive documentation will be provided once the base setup is complete.
