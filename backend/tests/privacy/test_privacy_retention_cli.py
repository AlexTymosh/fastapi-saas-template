from __future__ import annotations

from pathlib import Path

import pytest

from app.privacy import retention_cli
from app.privacy.maintenance import PrivacyRetentionMaintenanceSummary
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


def test_privacy_retention_cli_parser_accepts_ops_flags() -> None:
    args = retention_cli.build_parser().parse_args(
        ["--dry-run", "--batch-size", "25", "--quiet"]
    )

    assert args.dry_run is True
    assert args.batch_size == 25
    assert args.quiet is True


def test_privacy_retention_cli_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        run_async(retention_cli.run_once(batch_size=0))


def test_privacy_retention_cli_uses_post_commit_retention_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = object()
    calls: list[tuple[object, bool, int]] = []

    async def _run_pass(
        received_session_factory,
        *,
        dry_run: bool,
        limit: int,
    ) -> PrivacyRetentionMaintenanceSummary:
        calls.append((received_session_factory, dry_run, limit))
        return PrivacyRetentionMaintenanceSummary(
            expired_export_artifacts=1,
            anonymised_invites=0,
            scrubbed_outbox_events=0,
            minimised_audit_events=0,
            cleaned_dsr_idempotency_keys=0,
        )

    monkeypatch.setattr(
        retention_cli,
        "get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        retention_cli,
        "run_privacy_retention_pass",
        _run_pass,
    )

    summary = run_async(retention_cli.run_once(dry_run=False, batch_size=7))

    assert summary["expired_export_artifacts"] == 1
    assert calls == [(session_factory, False, 7)]


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
