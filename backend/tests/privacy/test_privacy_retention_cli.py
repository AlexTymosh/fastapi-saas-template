from __future__ import annotations

from pathlib import Path

import pytest

from app.privacy.retention_cli import build_parser, run_once
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


def test_privacy_retention_cli_parser_accepts_ops_flags() -> None:
    args = build_parser().parse_args(["--dry-run", "--batch-size", "25", "--quiet"])

    assert args.dry_run is True
    assert args.batch_size == 25
    assert args.quiet is True


def test_privacy_retention_cli_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        run_async(run_once(batch_size=0))


def test_taskfile_exposes_privacy_retention_runner_tasks() -> None:
    taskfile = Path(__file__).resolve().parents[3] / "Taskfile.yml"
    content = taskfile.read_text(encoding="utf-8")

    assert "privacy:retention:once:" in content
    assert "privacy:retention:dry-run:" in content
    assert "python -m app.privacy.retention_cli" in content


def test_env_example_keeps_auth_and_invite_delivery_runtime_examples() -> None:
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    content = env_example.read_text(encoding="utf-8")
    required_examples = (
        "AUTH__ENABLED=false",
        "AUTH__ISSUER_URL=http://keycloak.local:8080/realms/fastapi-saas",
        "AUTH__AUDIENCE=fastapi-api",
        "AUTH__ALLOWED_AUTHORIZED_PARTIES=fastapi-web",
        "AUTH__METADATA_VALIDATION=warn",
        "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY=",
        "OUTBOX__INVITE_DELIVERY_ENABLED=true",
        "OUTBOX__STALE_PROCESSING_TIMEOUT_SECONDS=300",
        "INVITE_DELIVERY__PROVIDER=noop",
        "INVITE_DELIVERY__ACCEPT_URL_TEMPLATE=",
        "INVITE_DELIVERY__SMTP_HOST=",
        "INVITE_DELIVERY__SMTP_START_TLS=true",
    )

    missing_examples = [item for item in required_examples if item not in content]

    assert missing_examples == []
