import pytest
from pydantic import ValidationError

from app.platform.schemas.platform_query import PlatformLimitedUserListQuery
from app.platform.schemas.platform_users import PlatformLimitedUserResponse

pytestmark = [pytest.mark.security, pytest.mark.privacy]


def test_limited_platform_user_query_does_not_define_exact_email_filter() -> None:
    assert "exact_email" not in PlatformLimitedUserListQuery.model_fields


def test_limited_platform_user_query_rejects_exact_email_filter() -> None:
    with pytest.raises(ValidationError):
        PlatformLimitedUserListQuery.model_validate(
            {"exact_email": "alice@example.invalid"}
        )


def test_limited_platform_user_response_does_not_expose_email() -> None:
    assert "email" not in PlatformLimitedUserResponse.model_fields
