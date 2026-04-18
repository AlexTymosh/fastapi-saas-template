import io
import json
import logging
from unittest.mock import patch

from app.core.context import request_id_ctx
from app.core.logging.factory import configure_logging, get_logger


def test_configure_logging_outputs_json_event() -> None:
    stream = io.StringIO()

    with patch("sys.stdout", stream):
        configure_logging(
            log_level="INFO",
            log_json=True,
            service_name="test-service",
            environment="test",
            version="0.1.0",
        )

        token = request_id_ctx.set("req-123")
        try:
            log = get_logger("test.logger")
            log.info("something_happened")
        finally:
            request_id_ctx.reset(token)

    output = stream.getvalue().strip()
    assert output

    record = json.loads(output)
    assert record["event"] == "something_happened"
    assert record["level"] == "info"
    assert record["logger"] == "test.logger"
    assert record["service"] == "test-service"
    assert record["environment"] == "test"
    assert record["version"] == "0.1.0"
    assert record["category"] == "application"
    assert record["request_id"] == "req-123"


def test_configure_logging_drops_none_values_in_json_output() -> None:
    stream = io.StringIO()

    with patch("sys.stdout", stream):
        configure_logging(
            log_level="INFO",
            log_json=True,
            service_name="test-service",
            environment="test",
            version="0.1.0",
        )

        log = get_logger("test.logger")
        log.info("something_happened", optional_value=None)

    output = stream.getvalue().strip()
    assert output

    record = json.loads(output)
    assert "optional_value" not in record


def test_configure_logging_outputs_console_event() -> None:
    stream = io.StringIO()

    with patch("sys.stdout", stream):
        configure_logging(
            log_level="INFO",
            log_json=False,
            service_name="test-service",
            environment="test",
            version="0.1.0",
        )

        log = get_logger("test.logger")
        log.info("something_happened", category="security")

    output = stream.getvalue()
    assert "something_happened" in output
    assert "security" in output
    assert "test.logger" in output


def test_configure_logging_does_not_duplicate_root_handlers() -> None:
    configure_logging(
        log_level="INFO",
        log_json=True,
        service_name="test-service",
        environment="test",
        version="0.1.0",
    )
    configure_logging(
        log_level="INFO",
        log_json=True,
        service_name="test-service",
        environment="test",
        version="0.1.0",
    )

    root_logger = logging.getLogger()
    app_handlers = [
        handler
        for handler in root_logger.handlers
        if handler.get_name() == "app_root_structlog_handler"
    ]
    assert len(app_handlers) == 1
