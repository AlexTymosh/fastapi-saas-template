from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ExportContext:
    artifact_id: UUID
    data_subject_request_id: UUID
    subject_user_id: UUID | None
    requester_user_id: UUID | None
    request_type: str
    request_status: str
    generated_at: datetime
    schema_version: str


class SubjectDataExporter:
    def export_subject_data(self, context: ExportContext) -> dict[str, object]:
        raise NotImplementedError
