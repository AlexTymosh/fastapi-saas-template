from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.security]


ROOT_DIR = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT_DIR / "docker" / "backend" / "Dockerfile"
RUNTIME_DOC = ROOT_DIR / "backend" / "docs" / "runtime-hardening.md"


def test_backend_dockerfile_runs_as_unprivileged_user() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "ARG APP_UID=" in content
    assert "ARG APP_GID=" in content
    assert "useradd" in content
    assert "--shell /usr/sbin/nologin" in content
    assert "USER app:app" in content
    assert content.rfind("USER app:app") > content.rfind("uv sync")


def test_backend_dockerfile_owns_runtime_application_files() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY --chown=app:app app /app/app" in content
    assert "COPY --chown=app:app migrations /app/migrations" in content
    assert "chown -R app:app /app" in content


def test_backend_dockerfile_keeps_minimal_runtime_surface() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "--no-install-recommends" in content
    assert "rm -rf /var/lib/apt/lists/*" in content
    assert "sudo" not in content.lower()


def test_runtime_hardening_document_covers_secrets_and_containers() -> None:
    content = RUNTIME_DOC.read_text(encoding="utf-8")

    required_sections = (
        "Runtime secrets",
        "Container runtime hardening",
        "No secrets in images",
        "non-root",
        "read-only root filesystem",
    )
    missing_sections = [item for item in required_sections if item not in content]

    assert missing_sections == []
