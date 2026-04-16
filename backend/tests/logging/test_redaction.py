from app.core.logging.processors import redact_sensitive_fields


def test_redacts_sensitive_fields() -> None:
    event = {
        "password": "secret123",
        "token": "abc",
        "authorization": "Bearer xyz",
    }

    result = redact_sensitive_fields(None, "info", event)

    assert result["password"] == "[REDACTED]"
    assert result["token"] == "[REDACTED]"
    assert result["authorization"] == "[REDACTED]"
