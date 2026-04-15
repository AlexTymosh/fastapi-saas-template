from app.core.errors.problem import ProblemDetails

COMMON_ERROR_RESPONSES = {
    400: {"model": ProblemDetails, "description": "Bad Request"},
    401: {"model": ProblemDetails, "description": "Unauthorized"},
    403: {"model": ProblemDetails, "description": "Forbidden"},
    404: {"model": ProblemDetails, "description": "Not Found"},
    422: {"model": ProblemDetails, "description": "Validation Error"},
    500: {"model": ProblemDetails, "description": "Internal Server Error"},
}

WRITE_ERROR_RESPONSES = {
    **COMMON_ERROR_RESPONSES,
    409: {"model": ProblemDetails, "description": "Conflict"},
}
