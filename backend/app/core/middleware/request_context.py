import re
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_ctx

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-:/]{0,127}$")


def _extract_request_id(
    headers: Headers,
    *,
    header_name: str,
    trust_incoming_request_id: bool,
) -> str | None:
    if not trust_incoming_request_id:
        return None

    value = headers.get(header_name)
    if not value:
        return None

    value = value.strip()
    if not value or len(value) > 128:
        return None

    if not _REQUEST_ID_RE.fullmatch(value):
        return None

    return value


class RequestContextMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = "X-Request-ID",
        trust_incoming_request_id: bool = True,
    ) -> None:
        self.app = app
        self.header_name = header_name
        self.trust_incoming_request_id = trust_incoming_request_id

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = _extract_request_id(
            headers,
            header_name=self.header_name,
            trust_incoming_request_id=self.trust_incoming_request_id,
        ) or str(uuid4())

        scope["request_id"] = request_id
        token = request_id_ctx.set(request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers[self.header_name] = request_id

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)
