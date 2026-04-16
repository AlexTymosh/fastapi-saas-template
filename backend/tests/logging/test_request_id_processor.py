from app.core.context import request_id_ctx
from app.core.logging.processors import add_request_id


def test_add_request_id_from_context() -> None:
    token = request_id_ctx.set("req-123")

    try:
        event = {"event": "something_happened"}
        result = add_request_id(None, "info", event)

        assert result["request_id"] == "req-123"
    finally:
        request_id_ctx.reset(token)
