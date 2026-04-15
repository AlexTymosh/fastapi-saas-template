from fastapi import APIRouter

from app.api.health import router as health_router

# Master API router
router = APIRouter()

# --- API version 1 router ---
v1_router = APIRouter()

# 001. Health check endpoint
v1_router.include_router(health_router, prefix="/health")

# Attach v1 router to the master router
router.include_router(v1_router, prefix="/api/v1")
