from fastapi import APIRouter

from app.health.api.health import router as health_router
from app.invites.api.invites import router as invites_router
from app.organisations.api.organisations import router as organisations_router
from app.platform.api.audit_events import router as platform_audit_events_router
from app.platform.api.identity import router as platform_identity_router
from app.platform.api.organisations import router as platform_organisations_router
from app.platform.api.staff import router as platform_staff_router
from app.platform.api.users import router as platform_users_router
from app.privacy.api.data_subject_requests import (
    router as privacy_data_subject_requests_router,
)
from app.privacy.api.export_artifacts import router as privacy_export_artifacts_router
from app.privacy.api.platform_data_subject_requests import (
    router as platform_privacy_data_subject_requests_router,
)
from app.privacy.api.platform_export_artifacts import (
    router as platform_privacy_export_artifacts_router,
)
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
    # 004. Invite endpoints
    v1_router.include_router(invites_router)
    # 005. Platform identity endpoint
    v1_router.include_router(platform_identity_router)
    # 006. Platform users endpoints
    v1_router.include_router(platform_users_router)
    # 007. Platform organisation endpoints
    v1_router.include_router(platform_organisations_router)
    # 008. Platform audit event endpoints
    v1_router.include_router(platform_audit_events_router)
    # 009. Platform staff management endpoints
    v1_router.include_router(platform_staff_router)
    # 010. Data subject requests self-service endpoints
    v1_router.include_router(privacy_data_subject_requests_router)
    # 011. Platform data subject requests endpoints
    v1_router.include_router(platform_privacy_data_subject_requests_router)
    # 012. Export artifacts self-service endpoints
    v1_router.include_router(privacy_export_artifacts_router)
    # 013. Platform export artifacts endpoints
    v1_router.include_router(platform_privacy_export_artifacts_router)

    router.include_router(v1_router, prefix=v1_prefix)
    return router
