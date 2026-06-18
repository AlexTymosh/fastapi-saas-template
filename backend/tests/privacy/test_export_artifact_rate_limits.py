from __future__ import annotations

from uuid import UUID

from app.core.rate_limit.identifiers import RateLimitBucket
from app.core.rate_limit.policies import PRIVACY_EXPORT_DOWNLOAD_URL_POLICY
from app.privacy import rate_limits
from tests.helpers.asyncio_runner import run_async


def test_export_download_url_rate_limit_uses_artifact_bucket(monkeypatch) -> None:
    artifact_id = UUID("00000000-0000-4000-8000-000000000123")
    calls: list[tuple[object, object, object]] = []
    request = object()

    async def fake_check_rate_limit_for_bucket(*, request, policy, bucket):
        calls.append((request, policy, bucket))

    monkeypatch.setattr(
        rate_limits,
        "check_rate_limit_for_bucket",
        fake_check_rate_limit_for_bucket,
    )

    run_async(
        rate_limits.check_export_artifact_download_url_rate_limit(
            request=request,
            artifact_id=artifact_id,
        )
    )

    assert calls == [
        (
            request,
            PRIVACY_EXPORT_DOWNLOAD_URL_POLICY,
            RateLimitBucket(
                kind="privacy_export_download_artifact",
                raw_value=f"artifact:{artifact_id}",
            ),
        )
    ]
