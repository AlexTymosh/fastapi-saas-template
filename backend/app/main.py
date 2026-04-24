from contextlib import asynccontextmanager

from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference
from starlette.responses import RedirectResponse

from app.api.master_router import build_master_router
from app.core.config.settings import Settings, get_settings
from app.core.db import dispose_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware.access_log import AccessLogMiddleware
from app.core.middleware.request_context import RequestContextMiddleware
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = get_logger(__name__)
    log.info("app_started")
    try:
        yield
    finally:
        await close_redis()
        await dispose_engine()
        log.info("app_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    configure_logging(
        log_level=resolved_settings.logging.level,
        log_json=resolved_settings.logging.as_json,
        service_name=resolved_settings.app.name,
        environment=resolved_settings.app.environment,
        version=resolved_settings.app.version,
    )

    app = FastAPI(
        title=resolved_settings.app.name,
        version=resolved_settings.app.version,
        openapi_url=(
            resolved_settings.api.openapi_url
            if resolved_settings.api.docs_enabled
            else None
        ),
        docs_url=(
            resolved_settings.api.docs_url if resolved_settings.api.docs_enabled else None
        ),
        redoc_url=(
            resolved_settings.api.redoc_url
            if resolved_settings.api.docs_enabled
            else None
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        RequestContextMiddleware,
        header_name=resolved_settings.request_context.header_name,
        trust_incoming_request_id=(
            resolved_settings.request_context.trust_incoming_request_id
        ),
    )
    app.add_middleware(AccessLogMiddleware)

    register_exception_handlers(
        app,
        request_id_header_name=resolved_settings.request_context.header_name,
    )
    app.include_router(build_master_router(v1_prefix=resolved_settings.api.v1_prefix))

    if resolved_settings.api.docs_enabled:

        @app.get(resolved_settings.api.scalar_path, include_in_schema=False)
        async def scalar_docs():
            return get_scalar_api_reference(openapi_url=app.openapi_url)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url=resolved_settings.api.scalar_path)

    return app


app = create_app()
