from fastapi import APIRouter, Response, status

from app.schemas.health import HealthLiveResponse, HealthReadyResponse
from app.services.health import get_readiness_status

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthLiveResponse, name="health_live")
async def health_live() -> HealthLiveResponse:
    return HealthLiveResponse(status="ok")


@router.get("/ready", response_model=HealthReadyResponse, name="health_ready")
async def health_ready(response: Response) -> HealthReadyResponse:
    result = await get_readiness_status()

    response.status_code = (
        status.HTTP_200_OK
        if result.status == "ok"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return result
