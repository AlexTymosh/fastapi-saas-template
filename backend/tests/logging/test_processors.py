import copy

import pytest

from app.core.context import request_id_ctx
from app.core.logging.processors import (
    add_request_id,
    ensure_category,
    redact_sensitive_fields,
)

REDACTED = "[REDACTED]"
MASKED_EMAIL_DOMAIN = "@example.invalid"
FAKE_EMAIL = "alex@example.invalid"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.c2lnbmF0dXJl"


def test_add_request_id_from_context() -> None:
    token = request_id_ctx.set("req-123")

    try:
        event = {"event": "something_happened"}
        result = add_request_id(None, "info", event)

        assert result["request_id"] == "req-123"
    finally:
        request_id_ctx.reset(token)


def test_add_request_id_does_not_override_existing_request_id() -> None:
    token = request_id_ctx.set("req-from-context")

    try:
        event = {
            "event": "something_happened",
            "request_id": "req-explicit",
        }
        result = add_request_id(None, "info", event)

        assert result["request_id"] == "req-explicit"
    finally:
        request_id_ctx.reset(token)


def test_ensure_category_sets_default_when_missing() -> None:
    processor = ensure_category(default_category="application")

    event = {"event": "something_happened"}
    result = processor(None, "info", event)

    assert result["category"] == "application"


def test_ensure_category_does_not_override_existing_value() -> None:
    processor = ensure_category(default_category="application")

    event = {
        "event": "something_happened",
        "category": "security",
    }
    result = processor(None, "info", event)

    assert result["category"] == "security"


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "api_key",
        "client_secret",
    ],
)
def test_redact_sensitive_fields_redacts_exact_sensitive_keys(key: str) -> None:
    event = {key: "safe-fake-sensitive-value"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result[key] == REDACTED


@pytest.mark.parametrize("key", ["raw-token", "x-api-key", "set-cookie"])
def test_redact_sensitive_fields_redacts_hyphenated_sensitive_keys(key: str) -> None:
    event = {key: "safe-fake-sensitive-value"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result[key] == REDACTED


@pytest.mark.parametrize("key", ["raw_token", "encrypted_raw_token", "token_hash"])
def test_redact_sensitive_fields_redacts_snake_case_sensitive_keys(key: str) -> None:
    event = {key: "safe-fake-sensitive-value"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result[key] == REDACTED


@pytest.mark.parametrize("key", ["clientSecret", "refreshToken", "AccessToken"])
def test_redact_sensitive_fields_redacts_camel_and_pascal_case_keys(
    key: str,
) -> None:
    event = {key: "safe-fake-sensitive-value"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result[key] == REDACTED


@pytest.mark.parametrize("key", ["Authorization", "authorizationHeader"])
def test_redact_sensitive_fields_redacts_authorization_key_variants(key: str) -> None:
    event = {key: "safe-fake-sensitive-value"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result[key] == REDACTED


def test_redact_sensitive_fields_redacts_nested_mappings() -> None:
    event = {
        "payload": {
            "email": FAKE_EMAIL,
            "raw-token": "safe-fake-sensitive-value",
            "details": {
                "clientSecret": "safe-fake-sensitive-value",
                "non_sensitive": "visible",
            },
        }
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["payload"]["raw-token"] == REDACTED
    assert result["payload"]["details"]["clientSecret"] == REDACTED
    assert result["payload"]["details"]["non_sensitive"] == "visible"
    assert result["payload"]["email"] != FAKE_EMAIL
    assert result["payload"]["email"].endswith(MASKED_EMAIL_DOMAIN)


def test_redact_sensitive_fields_redacts_list_of_mappings() -> None:
    event = {
        "items": [
            {"name": "first", "x-api-key": "safe-fake-sensitive-value"},
            {"name": "second", "token_hash": "safe-fake-sensitive-value"},
        ]
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["items"] == [
        {"name": "first", "x-api-key": REDACTED},
        {"name": "second", "token_hash": REDACTED},
    ]


def test_redact_sensitive_fields_redacts_tuple_of_mappings() -> None:
    event = {
        "items": (
            {"name": "first", "set-cookie": "safe-fake-sensitive-value"},
            {"name": "second", "refreshToken": "safe-fake-sensitive-value"},
        )
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["items"] == (
        {"name": "first", "set-cookie": REDACTED},
        {"name": "second", "refreshToken": REDACTED},
    )


@pytest.mark.parametrize(
    "value",
    [
        "Bearer safe-fake-token-value",
        "prefix bearer safe-fake-token-value",
        "Basic dXNlcjpwYXNz",
        "prefix basic dXNlcjpwYXNz",
        FAKE_JWT,
        f"prefix {FAKE_JWT} suffix",
    ],
)
def test_redact_sensitive_fields_redacts_sensitive_string_values(value: str) -> None:
    event = {"message": value}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["message"] == REDACTED


def test_redact_sensitive_fields_keeps_non_sensitive_fields_unchanged() -> None:
    event = {
        "event": "user_viewed_dashboard",
        "status": "ok",
        "count": 3,
        "metadata": {"description": "plain operational message"},
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result == event


def test_redact_sensitive_fields_masks_email() -> None:
    event = {
        "email": FAKE_EMAIL,
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["email"] != FAKE_EMAIL
    assert result["email"].endswith(MASKED_EMAIL_DOMAIN)


def test_redact_sensitive_fields_redacts_sensitive_key_with_email_value() -> None:
    event = {
        "inviteToken": FAKE_EMAIL,
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["inviteToken"] == REDACTED


def test_redact_sensitive_fields_does_not_mutate_input_event() -> None:
    event = {
        "payload": {
            "raw-token": "safe-fake-sensitive-value",
            "email": FAKE_EMAIL,
        },
        "items": ({"clientSecret": "safe-fake-sensitive-value"},),
    }
    original = copy.deepcopy(event)

    result = redact_sensitive_fields(None, "info", event)

    assert event == original
    assert result is not event
    assert result["payload"] is not event["payload"]
    assert result["items"] is not event["items"]
