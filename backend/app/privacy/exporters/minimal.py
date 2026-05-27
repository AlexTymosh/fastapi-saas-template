from __future__ import annotations

from app.privacy.exporters.base import ExportContext, SubjectDataExporter


class MinimalSubjectDataExporter(SubjectDataExporter):
    def export_subject_data(self, context: ExportContext) -> dict[str, object]:
        return {
            "schema_version": context.schema_version,
            "generated_at": context.generated_at.isoformat(),
            "data_subject_request_id": str(context.data_subject_request_id),
            "subject_user_id": (
                str(context.subject_user_id) if context.subject_user_id else None
            ),
            "requester_user_id": (
                str(context.requester_user_id) if context.requester_user_id else None
            ),
            "request_type": context.request_type,
            "request_status": context.request_status,
            "artifact_id": str(context.artifact_id),
        }
