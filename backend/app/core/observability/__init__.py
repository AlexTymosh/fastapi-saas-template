from app.core.observability.lifecycle import (
    init_observability,
    shutdown_observability,
)
from app.core.observability.metrics import (
    ALLOWED_HTTP_ATTRIBUTE_KEYS,
    ALLOWED_HTTP_ERROR_ATTRIBUTE_KEYS,
    ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS,
    get_route_template,
    record_http_error,
    record_http_request,
    record_http_request_duration,
    record_rate_limit_backend_error,
    record_rate_limit_check_duration,
    record_rate_limit_decision,
)
from app.core.observability.middleware import HttpMetricsMiddleware

__all__ = [
    "ALLOWED_HTTP_ATTRIBUTE_KEYS",
    "ALLOWED_HTTP_ERROR_ATTRIBUTE_KEYS",
    "ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS",
    "HttpMetricsMiddleware",
    "init_observability",
    "get_route_template",
    "record_http_error",
    "record_http_request",
    "record_http_request_duration",
    "record_rate_limit_backend_error",
    "record_rate_limit_check_duration",
    "record_rate_limit_decision",
    "shutdown_observability",
]
