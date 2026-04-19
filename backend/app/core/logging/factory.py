from __future__ import annotations

import logging
import sys

import structlog

from app.core.logging.processors import (
    add_request_id,
    add_service_context,
    drop_none_values,
    ensure_category,
    redact_sensitive_fields,
)


def configure_logging(
    *,
    log_level: str,
    log_json: bool,
    service_name: str,
    environment: str,
    version: str,
) -> None:
    structlog.reset_defaults()

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        add_service_context(
            service_name=service_name,
            environment=environment,
            version=version,
        ),
        add_request_id,
        ensure_category(default_category="application"),
        redact_sensitive_fields,
        drop_none_values,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.set_name("app_root_structlog_handler")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for existing_handler in list(root_logger.handlers):
        if existing_handler.get_name() == "app_root_structlog_handler":
            root_logger.removeHandler(existing_handler)
            existing_handler.close()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    logging.getLogger("uvicorn").handlers.clear()
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.error").handlers.clear()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
