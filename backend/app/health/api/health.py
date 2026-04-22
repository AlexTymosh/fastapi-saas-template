from fastapi import APIRouter, Response, status

from app.core.errors.openapi import COMMON_ERROR_RESPONSES, problem_response
from app.health.schemas.health import HealthLiveResponse, HealthReadyResponse
from app.health.services.health import get_readiness_status

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=HealthLiveResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="health_live",
)
async def health_live() -> HealthLiveResponse:
    return HealthLiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthReadyResponse,
    responses={
        **COMMON_ERROR_RESPONSES,
        503: problem_response("Service Unavailable"),
    },
    name="health_ready",
)
async def health_ready(response: Response) -> HealthReadyResponse:
    result = await get_readiness_status()

    response.status_code = (
        status.HTTP_200_OK
        if result.status == "ok"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return result
