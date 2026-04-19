from contextlib import asynccontextmanager

from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference
from starlette.responses import RedirectResponse

from app.api.master_router import build_master_router
from app.core.config.settings import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware.access_log import AccessLogMiddleware
from app.core.middleware.request_context import RequestContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = get_logger(__name__)
    log.info("app_started")
    try:
        yield
    finally:
        log.info("app_stopped")


def create_app() -> FastAPI:
    # App factory should always pick up latest env overrides in tests and runtime.
    get_settings.cache_clear()

    settings = get_settings()

    configure_logging(
        log_level=settings.logging.level,
        log_json=settings.logging.as_json,
        service_name=settings.app.name,
        environment=settings.app.environment,
        version=settings.app.version,
    )

    app = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        openapi_url=settings.api.openapi_url if settings.api.docs_enabled else None,
        docs_url=settings.api.docs_url if settings.api.docs_enabled else None,
        redoc_url=settings.api.redoc_url if settings.api.docs_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        RequestContextMiddleware,
        header_name=settings.request_context.header_name,
        trust_incoming_request_id=settings.request_context.trust_incoming_request_id,
    )
    app.add_middleware(AccessLogMiddleware)
    register_exception_handlers(
        app,
        request_id_header_name=settings.request_context.header_name,
    )
    app.include_router(build_master_router(v1_prefix=settings.api.v1_prefix))

    if settings.api.docs_enabled:

        @app.get(settings.api.scalar_path, include_in_schema=False)
        async def scalar_docs():
            return get_scalar_api_reference(openapi_url=app.openapi_url)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url=settings.api.scalar_path)

    return app


app = create_app()
