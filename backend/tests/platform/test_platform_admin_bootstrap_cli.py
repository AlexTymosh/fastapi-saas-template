from __future__ import annotations

from uuid import UUID

import pytest

from app.core.errors.exceptions import ConflictError
from app.platform.cli import bootstrap_admin
from app.platform.services.platform_bootstrap import (
    PlatformAdminBootstrapResult,
    PlatformAdminBootstrapStatus,
)
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security, pytest.mark.authz]


def test_bootstrap_cli_parser_requires_email() -> None:
    with pytest.raises(SystemExit):
        bootstrap_admin.build_parser().parse_args(
            ["--reason", "Initial platform admin bootstrap"]
        )


def test_bootstrap_cli_parser_requires_reason() -> None:
    with pytest.raises(SystemExit):
        bootstrap_admin.build_parser().parse_args(["--email", "admin@example.com"])


def test_bootstrap_cli_returns_failure_for_expected_validation_error(
    monkeypatch, capsys
) -> None:
    class FailingService:
        async def bootstrap_platform_admin_by_email(self, **kwargs):
            raise ConflictError(
                detail="Production platform bootstrap requires --confirm-production."
            )

    monkeypatch.setattr(
        bootstrap_admin, "PlatformAdminBootstrapService", FailingService
    )

    exit_code = run_async(
        bootstrap_admin._amain(  # noqa: SLF001
            [
                "--email",
                "admin@example.com",
                "--reason",
                "Initial platform admin bootstrap",
            ]
        )
    )

    assert exit_code == 1
    assert "confirm-production" in capsys.readouterr().err


def test_bootstrap_cli_passes_production_confirmation(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    class SuccessfulService:
        async def bootstrap_platform_admin_by_email(self, **kwargs):
            calls.append(kwargs)
            return PlatformAdminBootstrapResult(
                target_user_id=UUID("00000000-0000-0000-0000-000000000001"),
                platform_staff_id=UUID("00000000-0000-0000-0000-000000000002"),
                status=PlatformAdminBootstrapStatus.CREATED_STAFF,
                previous_role=None,
                previous_status=None,
                new_role="platform_admin",
                new_status="active",
                email="admin@example.com",
            )

    monkeypatch.setattr(
        bootstrap_admin, "PlatformAdminBootstrapService", SuccessfulService
    )

    exit_code = run_async(
        bootstrap_admin._amain(  # noqa: SLF001
            [
                "--email",
                "admin@example.com",
                "--reason",
                "Initial platform admin bootstrap",
                "--confirm-production",
            ]
        )
    )

    assert exit_code == 0
    assert calls[0]["confirm_production"] is True
    assert "created_staff" in capsys.readouterr().out
