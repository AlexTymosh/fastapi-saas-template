import re
from collections.abc import Sequence
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.core.context import get_request_id
from app.core.errors.codes import ErrorCode
from app.core.errors.exceptions import AppError, TooManyRequestsError
from app.core.errors.problem import InvalidParam, ProblemDetails

_HTTP_PROBLEM_MAPPING: dict[int, tuple[str, str, str]] = {
    HTTPStatus.BAD_REQUEST: (
        "problem:bad-request",
        "Bad Request",
        str(ErrorCode.BAD_REQUEST),
    ),
    HTTPStatus.UNAUTHORIZED: (
        "problem:unauthorized",
        "Unauthorized",
        str(ErrorCode.UNAUTHORIZED),
    ),
    HTTPStatus.FORBIDDEN: (
        "problem:forbidden",
        "Forbidden",
        str(ErrorCode.FORBIDDEN),
    ),
    HTTPStatus.NOT_FOUND: (
        "problem:not-found",
        "Resource not found",
        str(ErrorCode.NOT_FOUND),
    ),
    HTTPStatus.METHOD_NOT_ALLOWED: (
        "problem:method-not-allowed",
        "Method Not Allowed",
        str(ErrorCode.METHOD_NOT_ALLOWED),
    ),
    HTTPStatus.CONFLICT: (
        "problem:conflict",
        "Conflict",
        str(ErrorCode.CONFLICT),
    ),
    HTTPStatus.UNPROCESSABLE_ENTITY: (
        "problem:validation-error",
        "Request validation failed",
        str(ErrorCode.VALIDATION_ERROR),
    ),
}


def _slugify_http_status_phrase(value: str) -> str:
    normalized = value.lower().replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def _build_instance(request: Request) -> str:
    return request.url.path


def _get_request_id(request: Request) -> str | None:
    value = get_request_id()
    if value:
        return value

    scope_value = request.scope.get("request_id")
    return str(scope_value) if scope_value else None


def _problem_response(
    problem: ProblemDetails,
    *,
    request_id_header_name: str,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = get_request_id() or problem.request_id

    headers: dict[str, str] = {}
    if request_id:
        headers[request_id_header_name] = request_id
    if extra_headers:
        headers.update(extra_headers)

    return JSONResponse(
        status_code=problem.status,
        content=problem.to_dict(),
        media_type="application/problem+json",
        headers=headers,
    )


def _validation_errors_to_invalid_params(
    exc: RequestValidationError,
) -> list[InvalidParam]:
    result: list[InvalidParam] = []

    for err in exc.errors():
        loc: Sequence[str | int] = err.get("loc", ())
        msg = err.get("msg", "Invalid value")
        err_type = err.get("type")

        pointer = "/" + "/".join(str(item) for item in loc) if loc else None
        name = str(loc[-1]) if loc else "request"

        result.append(
            InvalidParam(
                name=name,
                reason=msg,
                pointer=pointer,
                code=err_type,
            )
        )

    return result


def _build_http_exception_problem(
    request: Request,
    exc: StarletteHTTPException,
) -> ProblemDetails:
    fallback_status = HTTPStatus.INTERNAL_SERVER_ERROR
    status_code = (
        exc.status_code
        if exc.status_code in HTTPStatus._value2member_map_
        else fallback_status
    )
    status = HTTPStatus(status_code)

    mapped = _HTTP_PROBLEM_MAPPING.get(status)
    if mapped:
        problem_type, title, error_code = mapped
    else:
        slug = _slugify_http_status_phrase(status.phrase)
        problem_type = f"problem:{slug}"
        title = status.phrase
        error_code = slug.replace("-", "_")

    detail = exc.detail if isinstance(exc.detail, str) else title

    return ProblemDetails(
        type=problem_type,
        title=title,
        status=status,
        detail=detail,
        instance=_build_instance(request),
        error_code=error_code,
        request_id=_get_request_id(request),
    )


def register_exception_handlers(
    app: FastAPI,
    *,
    request_id_header_name: str = "X-Request-ID",
) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        problem = ProblemDetails(
            type=exc.type,
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            instance=_build_instance(request),
            error_code=str(exc.error_code),
            request_id=_get_request_id(request),
            **exc.extra,
        )
        extra_headers: dict[str, str] = {}
        if isinstance(exc, TooManyRequestsError):
            retry_after = int(exc.extra.get("retry_after", 1))
            extra_headers["Retry-After"] = str(max(1, retry_after))
            extra_headers["Access-Control-Expose-Headers"] = "Retry-After"

        return _problem_response(
            problem,
            request_id_header_name=request_id_header_name,
            extra_headers=extra_headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        invalid_params = _validation_errors_to_invalid_params(exc)

        problem = ProblemDetails(
            type="problem:validation-error",
            title="Request validation failed",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="One or more request fields are invalid.",
            instance=_build_instance(request),
            error_code=str(ErrorCode.VALIDATION_ERROR),
            request_id=_get_request_id(request),
            errors=invalid_params,
        )
        return _problem_response(
            problem,
            request_id_header_name=request_id_header_name,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if exc.status_code == HTTPStatus.NOT_FOUND:
            problem = ProblemDetails(
                type="problem:not-found",
                title="Resource not found",
                status=HTTPStatus.NOT_FOUND,
                detail="The requested resource was not found.",
                instance=_build_instance(request),
                error_code=str(ErrorCode.NOT_FOUND),
                request_id=_get_request_id(request),
            )
            return _problem_response(
                problem,
                request_id_header_name=request_id_header_name,
            )

        problem = _build_http_exception_problem(request, exc)
        return _problem_response(
            problem,
            request_id_header_name=request_id_header_name,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        problem = ProblemDetails(
            type="problem:internal-error",
            title="Internal Server Error",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
            instance=_build_instance(request),
            error_code=str(ErrorCode.INTERNAL_ERROR),
            request_id=_get_request_id(request),
        )
        return _problem_response(
            problem,
            request_id_header_name=request_id_header_name,
        )
