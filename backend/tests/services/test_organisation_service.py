from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.errors.exceptions import BadRequestError, ConflictError
from app.organisations.services.organisations import OrganisationService
from tests.helpers.asyncio_runner import run_async


def test_create_organisation_raises_bad_request_for_blank_slug() -> None:
    service = OrganisationService(session=AsyncMock())
    service.organisation_repository = AsyncMock()

    with pytest.raises(BadRequestError):
        run_async(service.create_organisation(name="Acme", slug="   "))


def test_create_organisation_raises_bad_request_for_blank_name() -> None:
    service = OrganisationService(session=AsyncMock())
    service.organisation_repository = AsyncMock()

    with pytest.raises(BadRequestError):
        run_async(service.create_organisation(name="   ", slug="acme"))


def test_create_organisation_raises_conflict_for_existing_slug() -> None:
    service = OrganisationService(session=AsyncMock())

    repo = AsyncMock()
    repo.get_by_slug = AsyncMock(return_value=object())
    service.organisation_repository = repo

    with pytest.raises(ConflictError):
        run_async(service.create_organisation(name="Acme", slug="acme"))
