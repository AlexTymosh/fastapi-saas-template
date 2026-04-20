from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.errors.exceptions import BadRequestError, ConflictError
from app.organisations.models.organisation import Organisation
from app.organisations.services.organisations import OrganisationService
from tests.helpers.asyncio_runner import run_async


def test_create_organisation_rejects_blank_name_as_bad_request() -> None:
    service = OrganisationService(session=AsyncMock())

    with pytest.raises(BadRequestError):
        run_async(service.create_organisation(name="   ", slug="valid-slug"))


def test_create_organisation_rejects_invalid_slug_as_bad_request() -> None:
    service = OrganisationService(session=AsyncMock())

    with pytest.raises(BadRequestError):
        run_async(service.create_organisation(name="Acme", slug="Not Valid!"))


def test_create_organisation_keeps_conflict_for_slug_uniqueness() -> None:
    service = OrganisationService(session=AsyncMock())

    repo = AsyncMock()
    repo.get_by_slug = AsyncMock(return_value=Organisation(name="Acme", slug="taken"))
    service.organisation_repository = repo

    with pytest.raises(ConflictError):
        run_async(service.create_organisation(name="Acme", slug=" taken "))
