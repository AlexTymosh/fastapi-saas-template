import pytest

from app.commands.create_platform_admin import _run
from app.core.errors.exceptions import NotFoundError


@pytest.mark.asyncio
async def test_bootstrap_missing_user_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _run("missing@example.com")
