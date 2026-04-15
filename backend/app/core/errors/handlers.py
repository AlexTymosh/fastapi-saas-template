from collections.abc import Sequence
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.core.context import get_request_id
from app.core.errors.codes import ErrorCode
from app.core.errors.exceptions import AppError
from app.core.errors.problem import InvalidParam, ProblemDetails


def _build_instance(request: Request) -> str:
    return request.url.path


def _get_request_id(request: Request) -> str | None:
    value = get_request_id()
    if value:
        return value

    scope_value = request.scope.get("request_id")
    return str(scope_value) if scope_value else None


def _problem_response(problem: ProblemDetails) -> JSONResponse:
    request_id = get_request_id() or problem.request_id

    headers: dict[str, str] = {}
    if request_id:
        headers["X-Request-ID"] = request_id

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


def register_exception_handlers(app: FastAPI) -> None:
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
        return _problem_response(problem)

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
        return _problem_response(problem)

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
            return _problem_response(problem)

        detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"

        problem = ProblemDetails(
            type="about:blank",
            title=detail,
            status=exc.status_code,
            detail=detail,
            instance=_build_instance(request),
            request_id=_get_request_id(request),
        )
        return _problem_response(problem)

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
        return _problem_response(problem)
