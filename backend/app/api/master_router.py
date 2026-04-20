from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.organisations import router as organisations_router
from app.api.users import router as users_router


def build_master_router(*, v1_prefix: str) -> APIRouter:
    # Master API router
    router = APIRouter()

    # --- API version 1 router ---
    v1_router = APIRouter()

    # 001. Health check endpoint
    v1_router.include_router(health_router)
    # 002. User projection endpoints
    v1_router.include_router(users_router)
    # 003. Organisation and membership endpoints
    v1_router.include_router(organisations_router)

    # Attach v1 router to the master router
    router.include_router(v1_router, prefix=v1_prefix)
    return router
