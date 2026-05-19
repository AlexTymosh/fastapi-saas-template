from __future__ import annotations

import hmac
from http import HTTPStatus

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config.settings import Settings, get_settings
from app.core.context import get_request_id
from app.core.errors.codes import ErrorCode
from app.core.errors.exceptions import (
    AppError,
    RateLimiterUnavailableError,
    TooManyRequestsError,
)
from app.core.errors.problem import ProblemDetails
from app.core.rate_limit.dependencies import check_pre_auth_rate_limit
from app.core.rate_limit.identifiers import is_request_from_trusted_proxy

_DEFAULT_EXCLUDED_PATH_SUFFIXES = (
    "/health/live",
    "/health/ready",
)


class RateLimitIngressMiddleware:
    """Ingress security layer for pre-auth throttling and edge-only deployments.

    Endpoint-level dependencies still own authenticated business rate limits. This
    middleware adds only the controls that must run before authentication:
    IP/client pre-auth throttling and trusted-edge assertion verification.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str = "/api/v1",
        request_id_header_name: str = "X-Request-ID",
    ) -> None:
        self.app = app
        self.api_prefix = api_prefix.rstrip("/") or "/api/v1"
        self.request_id_header_name = request_id_header_name

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = _settings_from_scope(scope)
        request = Request(scope, receive=receive)

        if (
            settings.rate_limiting.enforced_by_edge
            and _should_apply_edge_assertion(
                scope=scope,
                api_prefix=self.api_prefix,
            )
            and not _has_valid_edge_assertion(
                request=request,
                settings=settings,
            )
        ):
            await _send_problem_response(
                send,
                status=HTTPStatus.FORBIDDEN,
                problem_type="problem:forbidden",
                title="Forbidden",
                detail="Direct origin access is not allowed.",
                error_code=str(ErrorCode.FORBIDDEN),
                instance=str(scope.get("path") or ""),
                request_id_header_name=self.request_id_header_name,
                extra_headers=None,
            )
            return

        if _should_apply_pre_auth_rate_limit(
            scope=scope,
            api_prefix=self.api_prefix,
            settings=settings,
        ):
            try:
                await check_pre_auth_rate_limit(request=request)
            except (TooManyRequestsError, RateLimiterUnavailableError) as exc:
                await _send_app_error_response(
                    send,
                    exc=exc,
                    instance=str(scope.get("path") or ""),
                    request_id_header_name=self.request_id_header_name,
                )
                return

        await self.app(scope, receive, send)


def _settings_from_scope(scope: Scope) -> Settings:
    app = scope.get("app")
    if app is not None:
        state = getattr(app, "state", None)
        settings = getattr(state, "settings", None)
        if settings is not None:
            return settings
    return get_settings()


def _is_excluded_api_path(*, scope: Scope, api_prefix: str) -> bool:
    path = str(scope.get("path") or "")
    if not path.startswith(api_prefix + "/"):
        return False

    suffix = path.removeprefix(api_prefix).rstrip("/")
    return suffix in _DEFAULT_EXCLUDED_PATH_SUFFIXES


def _should_apply_edge_assertion(
    *,
    scope: Scope,
    api_prefix: str,
) -> bool:
    method = str(scope.get("method") or "").upper()
    if method == "OPTIONS":
        return False

    path = str(scope.get("path") or "")
    if not path.startswith(api_prefix + "/"):
        return False

    return not _is_excluded_api_path(scope=scope, api_prefix=api_prefix)


def _should_apply_pre_auth_rate_limit(
    *,
    scope: Scope,
    api_prefix: str,
    settings: Settings,
) -> bool:
    if not settings.rate_limiting.enabled or not getattr(
        settings.rate_limiting, "pre_auth_enabled", False
    ):
        return False

    method = str(scope.get("method") or "").upper()
    if method == "OPTIONS":
        return False

    path = str(scope.get("path") or "")
    if not path.startswith(api_prefix + "/"):
        return False

    return not _is_excluded_api_path(scope=scope, api_prefix=api_prefix)


def _has_valid_edge_assertion(*, request: Request, settings: Settings) -> bool:
    if not is_request_from_trusted_proxy(
        request=request,
        trusted_proxy_cidrs=settings.rate_limiting.trusted_proxy_cidrs,
    ):
        return False

    header_name = settings.rate_limiting.edge_assertion_header_name
    secret = settings.rate_limiting.edge_assertion_secret
    if header_name is None or secret is None:
        return False

    headers = Headers(scope=request.scope)
    provided_value = headers.get(header_name)
    if provided_value is None:
        return False

    return hmac.compare_digest(provided_value, secret.get_secret_value())


async def _send_app_error_response(
    send: Send,
    *,
    exc: AppError,
    instance: str,
    request_id_header_name: str,
) -> None:
    await _send_problem_response(
        send,
        status=HTTPStatus(exc.status_code),
        problem_type=exc.type,
        title=exc.title,
        detail=exc.detail,
        error_code=str(exc.error_code),
        instance=instance,
        request_id_header_name=request_id_header_name,
        extra_headers=exc.headers,
    )


async def _send_problem_response(
    send: Send,
    *,
    status: HTTPStatus,
    problem_type: str,
    title: str,
    detail: str | None,
    error_code: str,
    instance: str,
    request_id_header_name: str,
    extra_headers: dict[str, str] | None,
) -> None:
    request_id = get_request_id()
    problem = ProblemDetails(
        type=problem_type,
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        error_code=error_code,
        request_id=request_id,
    )

    headers: dict[str, str] = {}
    if request_id:
        headers[request_id_header_name] = request_id
    if extra_headers:
        headers.update(extra_headers)

    response = JSONResponse(
        status_code=int(status),
        content=problem.to_dict(),
        media_type="application/problem+json",
        headers=headers,
    )
    await response(scope={"type": "http"}, receive=_empty_receive, send=send)


async def _empty_receive():  # pragma: no cover
    return {"type": "http.request", "body": b"", "more_body": False}
