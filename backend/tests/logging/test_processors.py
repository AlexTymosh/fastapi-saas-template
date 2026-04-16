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


def test_redact_sensitive_fields_redacts_flat_fields() -> None:
    event = {
        "password": "secret123",
        "token": "abc",
        "authorization": "Bearer xyz",
        "cookie": "session=123",
        "api_key": "key-123",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["password"] == "[REDACTED]"
    assert result["token"] == "[REDACTED]"
    assert result["authorization"] == "[REDACTED]"
    assert result["cookie"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"


def test_redact_sensitive_fields_masks_email() -> None:
    event = {
        "email": "alex@example.com",
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["email"] != "alex@example.com"
    assert result["email"].endswith("@example.com")


def test_redact_sensitive_fields_redacts_nested_mapping() -> None:
    event = {
        "payload": {
            "email": "alex@example.com",
            "token": "abc123",
            "password": "secret123",
        }
    }

    result = redact_sensitive_fields(None, "info", copy.deepcopy(event))

    assert result["payload"]["token"] == "[REDACTED]"
    assert result["payload"]["password"] == "[REDACTED]"
    assert result["payload"]["email"] != "alex@example.com"
    assert result["payload"]["email"].endswith("@example.com")
