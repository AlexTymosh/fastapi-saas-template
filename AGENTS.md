# AGENTS.md

## Purpose
Execution contract for AI coding agents. Enforce architecture, constraints, and patterns. Prefer consistency over creativity.

## Instruction Priority
1) User task
2) This file
3) Existing repo patterns
4) README
5) Framework defaults

## Architecture (Modular Monolith)

### Layers
- api
- services
- repositories
- schemas
- models
- core

### Rules
- API MUST NOT contain business logic
- Services contain business logic and orchestration
- Repositories handle DB only
- No DB access from API layer
- No raw SQL outside repositories (unless justified)

## Structure
- Keep files cohesive (<300–400 LOC target)
- No catch-all modules (utils/helpers) without narrow scope
- Prefer domain folders:

backend/app/<domain>/
  api/
  services/
  repositories/
  schemas/
  models/

## FastAPI Rules
- Use APIRouter
- Version routes: /api/v1
- Thin handlers
- Dependency Injection (Depends), no hidden globals
- Use async only for DB / external calls
- Pure CPU logic MUST be sync

### API Responses
Single resource (clean REST), example:
{
  "id": "123",
  "name": "Example"
}

Collection (envelope), example:
{
  "data": [
    { "id": 1 },
    { "id": 2 }
  ],
  "meta": {
    "page": 1,
    "pageSize": 20,
    "total": 999
  },
  "links": {
    "next": "/resources?page=2"
  }
}

Errors (RFC-style):
{
  "type": "https://api.example.com/errors/validation-error",
  "title": "Validation Error",
  "status": 400,
  "detail": "Email is invalid",
  "instance": "/users"
}

## Code Patterns (MANDATORY)

### API
- Each router MUST define tags
- Routers SHOULD be registered in deterministic order (001, 002, ...)
- Route paths MUST be defined inside router files
- Each router MUST be defined in a separate file under api/
- One file = one router
- File name SHOULD reflect domain or purpose (e.g. health.py, users.py)
- All routes MUST be attached to versioned router (`v1_router`)
- Version router MUST be attached to root router with prefix `/api/v1`
- DO NOT use prefix in include_router (except version prefix)
Example:

```
# app/api/health.py

from fastapi import APIRouter
router = APIRouter(tags=["health"])
@router.get("/health/live")
async def health_live():
    return {"status": "ok"}
```

Router registration (single entry point)
ALL routers MUST be registered in master_router.py
DO NOT register routers in main.py

Example:
```
# app/api/master_router.py

from fastapi import APIRouter
from app.api.health import router as health_router

router = APIRouter()

# --- API version 1 router ---
v1_router = APIRouter()

# --- Attach routes ---
# 001. Health check endpoint
v1_router.include_router(health_router)

# --- Attach version router ---
router.include_router(v1_router, prefix="/api/v1")
```



### Error Handling

Global exception handling MUST be implemented.

#### Rules

- API MUST NOT contain try/except for business logic  
- Services MUST raise exceptions and NOT return HTTP responses  
- All exceptions MUST be handled centrally via FastAPI handlers  

---

#### Handlers

- Domain-specific exceptions MUST be handled via `AppError` subclasses and a shared global handler
- A global fallback handler MUST exist:

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "type": "https://api.example.com/problems/internal-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred.",
            "instance": request.url.path,
            "error_code": "internal_error",
        },
        media_type="application/problem+json",
    )
```

##### Requirements
- All API error responses MUST use application/problem+json
- Error responses MUST follow the ProblemDetails schema
- HTTP status codes MUST match the error type
- Validation errors SHOULD include field-level details in errors
- Internal details MUST NOT be exposed
##### Anti-Patterns (MUST NOT)
- Format error responses inside endpoints
- Return raw exception messages
- Duplicate error handling logic
- Raise HTTPException from business/service layers


### Service
class ItemService:
    def __init__(self, repo: "ItemRepository"):
        self.repo = repo

    async def list_items(self):
        return await self.repo.get_all()

### Repository
class ItemRepository:
    async def get_all(self):
        ...

## Typing
- Type hints REQUIRED for public/core functions
- Use Pydantic for request/response
- Avoid untyped dicts in API

## Data & Persistence
- UUID PKs (ORM level)
- Access DB via repositories only
- Do not expose ORM models directly as API responses

## Auth / AuthZ
- JWT (Keycloak direction)
- Separate authentication from authorization
- Put permission logic in services

## Logging (enforced rules)
- Structured JSON logging
- NEVER log:
  - passwords
  - tokens
  - API keys
  - raw personal data (email, IP)
- Mask or hash identifiers when needed

## Security
- Validate all input via schemas
- Do not trust client-provided identifiers
- Avoid leaking internals in errors
- Consider rate limiting for public endpoints

## Configuration
- Env-based config
- No secrets in code
- No hardcoded credentials or URLs

## Testing
- Location: /tests
- Levels: unit / integration / contract

Rules:
- Test business logic (services)
- Mock external dependencies in unit tests
- Cover API behavior via integration tests

## Tooling
- Black (format)
- isort (imports)
- Ruff (lint)
- pytest
- pre-commit

Generated code should pass lint/format without manual fixes.

## Change Rules
- Read existing code first
- Follow existing patterns
- Minimal necessary changes
- Add/update tests when behavior changes

## Forbidden
- Business logic in API
- DB access outside repositories
- Logging sensitive data
- Hardcoded secrets
- New frameworks without need
- Over-abstraction

## Flow
HTTP → API → Service → Repository → Service → Response
