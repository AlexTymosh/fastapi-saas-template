from fastapi import APIRouter

from app.api.health import router as health_router
from app.organisations.api.organisations import router as organisations_router
from app.users.api.users import router as users_router


def build_master_router(*, v1_prefix: str) -> APIRouter:
    router = APIRouter()
    v1_router = APIRouter()

    # 001. Health check endpoint
    v1_router.include_router(health_router)
    # 002. Current user projection endpoint
    v1_router.include_router(users_router)
    # 003. Organisations and memberships endpoints
    v1_router.include_router(organisations_router)

    router.include_router(v1_router, prefix=v1_prefix)
    return router
