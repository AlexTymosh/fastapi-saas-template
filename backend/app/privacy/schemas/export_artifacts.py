from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExportArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    data_subject_request_id: UUID
    status: str
    format: str
    content_type: str | None
    size_bytes: int | None
    checksum_sha256: str | None
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    expires_at: datetime
    download_count: int


class ExportArtifactsMeta(BaseModel):
    total: int
    limit: int
    offset: int


class ExportArtifactsCollectionResponse(BaseModel):
    data: list[ExportArtifactResponse]
    meta: ExportArtifactsMeta
    links: dict[str, str]


class ExportDownloadUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int
