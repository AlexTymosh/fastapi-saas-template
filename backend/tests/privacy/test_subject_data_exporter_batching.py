from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.privacy.exporters import subject_data
from app.privacy.models.privacy_governance import (
    DataProcessingAuthorization,
    LawfulBasis,
    ProcessingPurpose,
    ProcessingPurposeFamily,
)
from app.privacy.providers.base import PrivacyProviderContext
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


def test_subject_export_providers_do_not_use_eager_all_loading() -> None:
    source = inspect.getsource(subject_data)

    assert ".all(" not in source
    assert "fetchmany(" in source
    assert "_iter_model_keyset" in source
    assert "_iter_row_keyset" in source
    assert "id_column > last_id" in source


def test_authorization_export_provider_iterates_keyset_batches(
    migrated_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subject_data, "_EXPORT_PROVIDER_BATCH_SIZE", 2)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            created_at = datetime.now(UTC) - timedelta(minutes=5)
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"batch-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(user)
            await session.flush()

            authorizations: list[DataProcessingAuthorization] = []
            for index in range(5):
                purpose = ProcessingPurpose(
                    code=f"batch-purpose-{uuid4()}",
                    title=f"Batch purpose {index}",
                    family=ProcessingPurposeFamily.ACCOUNT.value,
                    default_lawful_basis=LawfulBasis.CONTRACT.value,
                )
                session.add(purpose)
                await session.flush()

                authorization = DataProcessingAuthorization(
                    subject_user_id=user.id,
                    purpose_id=purpose.id,
                    lawful_basis=LawfulBasis.CONTRACT.value,
                    active=True,
                )
                authorization.created_at = created_at + timedelta(seconds=index)
                session.add(authorization)
                authorizations.append(authorization)
            await session.flush()

            context = PrivacyProviderContext(
                data_subject_request_id=uuid4(),
                subject_user_id=user.id,
                requester_user_id=user.id,
                schema_version="1.0",
            )
            records = []
            provider = subject_data.ProcessingAuthorizationsExportProvider(session)
            async for record in provider.iter_export_records(context):
                records.append(record)

            expected_ids = [authorization.id for authorization in authorizations]
            actual_ids = [UUID(str(record.payload["id"])) for record in records]

            assert actual_ids == expected_ids
            assert len(actual_ids) == 5

    run_async(_run())
