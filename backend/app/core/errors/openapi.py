from app.core.errors.problem import ProblemDetails


def problem_response(description: str) -> dict:
    return {
        "model": ProblemDetails,
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
    }


COMMON_ERROR_RESPONSES = {
    400: problem_response("Bad Request"),
    401: problem_response("Unauthorized"),
    403: problem_response("Forbidden"),
    404: problem_response("Not Found"),
    422: problem_response("Validation Error"),
    500: problem_response("Internal Server Error"),
}

WRITE_ERROR_RESPONSES = {
    **COMMON_ERROR_RESPONSES,
    409: problem_response("Conflict"),
}


RATE_LIMIT_ERROR_RESPONSES = {
    429: problem_response("Too Many Requests"),
    503: problem_response("Rate Limiter Unavailable"),
}
