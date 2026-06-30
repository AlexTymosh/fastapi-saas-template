# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ARG APP_UID=10001
ARG APP_GID=10001

COPY --from=ghcr.io/astral-sh/uv:0.7.22 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV UV_PROJECT_ENVIRONMENT=/usr/local
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${APP_GID}" --system app \
    && useradd \
        --uid "${APP_UID}" \
        --gid app \
        --system \
        --create-home \
        --home-dir /home/app \
        --shell /usr/sbin/nologin \
        app \
    && chown app:app /app /home/app

COPY pyproject.toml uv.lock README.md alembic.ini /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project

COPY --chown=app:app app /app/app
COPY --chown=app:app migrations /app/migrations

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable \
    && chown -R app:app /app

USER app:app

WORKDIR /app
