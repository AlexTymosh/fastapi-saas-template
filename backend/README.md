# Fastapi-SaaS-Template Backend

Backend package for the FastAPI SaaS template.

For project overview, architecture, and setup instructions, see the repository root README.

## Backend documentation entry points

- OpenAPI schema: `/openapi.json`
- Scalar UI: `/scalar`

## Tooling and project configuration

- Project metadata, dependencies, and tooling are configured in `pyproject.toml`.
- Development dependencies are declared as optional dependencies in
  `[project.optional-dependencies].dev`.
- Linting and formatting use Ruff and `ruff format`.

## Current membership contract

- A user can have only one active organisation membership at a time.
- Multiple active organisations per user are not currently supported.
- Historical (inactive) membership rows are retained for transfer history.
