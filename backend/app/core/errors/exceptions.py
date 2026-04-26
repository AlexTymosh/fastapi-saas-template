from http import HTTPStatus

from app.core.errors.codes import ErrorCode


class AppError(Exception):
    status_code: int = HTTPStatus.BAD_REQUEST
    title: str = "Application error"
    error_code: ErrorCode = ErrorCode.BAD_REQUEST
    type: str = "problem:application-error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        status_code: int | None = None,
        title: str | None = None,
        error_code: ErrorCode | None = None,
        type: str | None = None,
        extra: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail
        self.status_code = int(status_code or self.status_code)
        self.title = title or self.title
        self.error_code = error_code or self.error_code
        self.type = type or self.type
        self.extra = extra or {}
        self.headers = headers or {}
        super().__init__(detail or self.title)


class BadRequestError(AppError):
    status_code = HTTPStatus.BAD_REQUEST
    title = "Bad Request"
    error_code = ErrorCode.BAD_REQUEST
    type = "problem:bad-request"


class UnauthorizedError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    title = "Unauthorized"
    error_code = ErrorCode.UNAUTHORIZED
    type = "problem:unauthorized"


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    title = "Forbidden"
    error_code = ErrorCode.FORBIDDEN
    type = "problem:forbidden"


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    title = "Resource not found"
    error_code = ErrorCode.NOT_FOUND
    type = "problem:not-found"


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    title = "Conflict"
    error_code = ErrorCode.CONFLICT
    type = "problem:conflict"


class TooManyRequestsError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    title = "Too Many Requests"
    error_code = ErrorCode.RATE_LIMITED
    type = "problem:rate-limited"


class RateLimiterUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "Service Unavailable"
    error_code = ErrorCode.RATE_LIMITER_UNAVAILABLE
    type = "problem:rate-limiter-unavailable"
