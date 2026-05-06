import copy

from app.core.context import request_id_ctx
from app.core.logging.processors import (
    add_request_id,
    ensure_category,
    redact_sensitive_fields,
)


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


def test_redact_sensitive_fields_redacts_exact_sensitive_keys() -> None:
    event = {
        "password": "fake-password",
        "token": "fake-token",
        "authorization": "Bearer fake-token",
        "cookie": "session=fake-session",
        "api_key": "fake-api-key",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result == {
        "password": "[REDACTED]",
        "token": "[REDACTED]",
        "authorization": "[REDACTED]",
        "cookie": "[REDACTED]",
        "api_key": "[REDACTED]",
    }


def test_redact_sensitive_fields_redacts_hyphenated_keys() -> None:
    event = {
        "raw-token": "fake-raw-token",
        "x-api-key": "fake-api-key",
        "set-cookie": "session=fake-session",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["raw-token"] == "[REDACTED]"
    assert result["x-api-key"] == "[REDACTED]"
    assert result["set-cookie"] == "[REDACTED]"


def test_redact_sensitive_fields_redacts_snake_case_keys() -> None:
    event = {
        "raw_token": "fake-raw-token",
        "encrypted_raw_token": "fake-encrypted-raw-token",
        "token_hash": "fake-token-hash",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["raw_token"] == "[REDACTED]"
    assert result["encrypted_raw_token"] == "[REDACTED]"
    assert result["token_hash"] == "[REDACTED]"


def test_redact_sensitive_fields_redacts_camel_and_pascal_case_keys() -> None:
    event = {
        "clientSecret": "fake-client-secret",
        "refreshToken": "fake-refresh-token",
        "AccessToken": "fake-access-token",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["clientSecret"] == "[REDACTED]"
    assert result["refreshToken"] == "[REDACTED]"
    assert result["AccessToken"] == "[REDACTED]"


def test_redact_sensitive_fields_redacts_authorization_variants() -> None:
    event = {
        "Authorization": "Bearer fake-token",
        "authorizationHeader": "Bearer fake-token",
        "auth_header": "Basic fake-credentials",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["Authorization"] == "[REDACTED]"
    assert result["authorizationHeader"] == "[REDACTED]"
    assert result["auth_header"] == "[REDACTED]"


def test_redact_sensitive_fields_redacts_nested_mappings() -> None:
    event = {
        "payload": {
            "email": "alex@example.com",
            "token": "fake-token",
            "details": {
                "client-secret": "fake-client-secret",
                "safe_field": "visible",
            },
        }
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["payload"]["token"] == "[REDACTED]"
    assert result["payload"]["details"]["client-secret"] == "[REDACTED]"
    assert result["payload"]["details"]["safe_field"] == "visible"
    assert result["payload"]["email"] != "alex@example.com"
    assert result["payload"]["email"].endswith("@example.com")


def test_redact_sensitive_fields_redacts_list_of_mappings() -> None:
    event = {
        "items": [
            {"name": "public", "raw-token": "fake-raw-token"},
            {"name": "public-2", "x-api-key": "fake-api-key"},
        ]
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["items"] == [
        {"name": "public", "raw-token": "[REDACTED]"},
        {"name": "public-2", "x-api-key": "[REDACTED]"},
    ]


def test_redact_sensitive_fields_redacts_tuple_of_mappings() -> None:
    event = {
        "items": (
            {"name": "public", "refreshToken": "fake-refresh-token"},
            {"name": "public-2", "set-cookie": "session=fake-session"},
        )
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["items"] == (
        {"name": "public", "refreshToken": "[REDACTED]"},
        {"name": "public-2", "set-cookie": "[REDACTED]"},
    )


def test_redact_sensitive_fields_redacts_bearer_values() -> None:
    event = {"message": "upstream returned Bearer fake-token"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["message"] == "[REDACTED]"


def test_redact_sensitive_fields_redacts_basic_authorization_values() -> None:
    event = {"message": "upstream returned Basic fake-credentials"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["message"] == "[REDACTED]"


def test_redact_sensitive_fields_redacts_jwt_like_values() -> None:
    event = {"message": "JWT eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.fakeSignature"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["message"] == "[REDACTED]"


def test_redact_sensitive_fields_keeps_non_sensitive_fields_unchanged() -> None:
    event = {
        "event": "something_happened",
        "status": "ok",
        "nested": {"safe_field": "visible"},
        "items": ["visible", {"safe_field": "also-visible"}],
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result == event


def test_redact_sensitive_fields_masks_email() -> None:
    event = {
        "email": "alex@example.com",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["email"] != "alex@example.com"
    assert result["email"] == "a***x@example.com"


def test_redact_sensitive_fields_redacts_sensitive_key_with_email_value() -> None:
    event = {"inviteToken": "alex@example.com"}

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["inviteToken"] == "[REDACTED]"


def test_redact_sensitive_fields_does_not_mutate_original_event_dict() -> None:
    event = {
        "payload": {
            "email": "alex@example.com",
            "token": "fake-token",
        },
        "items": [{"clientSecret": "fake-client-secret"}],
    }
    original = copy.deepcopy(event)

    result = redact_sensitive_fields(None, "info", event)

    assert result is not event
    assert result["payload"] is not event["payload"]
    assert result["items"] is not event["items"]
    assert event == original
