from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data import (
    _EXPORT_PROVIDER_TYPES,
    SubjectDataExportError,
    _serialise_record,
)
from app.privacy.providers.base import PrivacyProviderContext

_JSON_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))


def _json_key(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + ":"


def _json_chunks(value: object) -> Iterable[str]:
    return _JSON_ENCODER.iterencode(value)


async def iter_subject_export_json_chunks(
    session: AsyncSession,
    context: ExportContext,
) -> AsyncIterator[str]:
    """Yield a DSR subject export JSON document without materialising it.

    The exported object keeps the existing schema keys while allowing archive
    generation to write each provider record directly into the ZIP member.
    """

    if context.subject_user_id is None:
        raise SubjectDataExportError("subject_user_missing")

    provider_context = PrivacyProviderContext(
        data_subject_request_id=context.data_subject_request_id,
        subject_user_id=context.subject_user_id,
        requester_user_id=context.requester_user_id,
        schema_version=context.schema_version,
    )
    providers = [provider_type(session) for provider_type in _EXPORT_PROVIDER_TYPES]
    provider_keys: list[str] = []
    redaction_notices: list[dict[str, object]] = []
    record_count = 0

    yield "{"
    header_fields: tuple[tuple[str, object], ...] = (
        ("schema_version", context.schema_version),
        ("generated_at", context.generated_at.isoformat()),
        ("data_subject_request_id", str(context.data_subject_request_id)),
        ("subject_user_id", str(context.subject_user_id)),
        (
            "requester_user_id",
            str(context.requester_user_id) if context.requester_user_id else None,
        ),
        ("request_type", context.request_type),
        ("request_status", context.request_status),
        ("artifact_id", str(context.artifact_id)),
    )
    for index, (key, value) in enumerate(header_fields):
        if index:
            yield ","
        yield _json_key(key)
        for chunk in _json_chunks(value):
            yield chunk

    yield ","
    yield _json_key("data")
    yield "{"
    for provider_index, provider in enumerate(providers):
        if provider_index:
            yield ","
        provider_keys.append(provider.provider_key)
        yield _json_key(provider.provider_key)
        yield "["
        first_record = True
        try:
            async for record in provider.iter_export_records(provider_context):
                if not first_record:
                    yield ","
                first_record = False
                record_count += 1
                if record.redacted_fields:
                    redaction_notices.append(
                        {
                            "provider_key": record.provider_key,
                            "table_name": record.table_name,
                            "redacted_fields": list(record.redacted_fields),
                            "reason_code": "non_exportable_or_review_required",
                        }
                    )
                for chunk in _json_chunks(_serialise_record(record)):
                    yield chunk
        except SubjectDataExportError:
            raise
        except Exception as exc:
            raise SubjectDataExportError("export_provider_failed") from exc
        yield "]"
    yield "}"

    manifest = {
        "format": "privacy_subject_export",
        "provider_count": len(provider_keys),
        "record_count": record_count,
        "providers": provider_keys,
        "redaction_notices": redaction_notices,
    }
    yield ","
    yield _json_key("manifest")
    for chunk in _json_chunks(manifest):
        yield chunk
    yield "}"
