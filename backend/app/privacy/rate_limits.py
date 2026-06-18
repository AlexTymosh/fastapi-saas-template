from __future__ import annotations

from uuid import UUID

from fastapi import Request

from app.core.rate_limit import RateLimitBucket, check_rate_limit_for_bucket
from app.core.rate_limit.policies import PRIVACY_EXPORT_DOWNLOAD_URL_POLICY


async def check_export_artifact_download_url_rate_limit(
    *,
    request: Request,
    artifact_id: UUID,
) -> None:
    """Apply an artifact-scoped bucket after export artifact authorization."""
    await check_rate_limit_for_bucket(
        request=request,
        policy=PRIVACY_EXPORT_DOWNLOAD_URL_POLICY,
        bucket=RateLimitBucket(
            kind="privacy_export_download_artifact",
            raw_value=f"artifact:{artifact_id}",
        ),
    )
