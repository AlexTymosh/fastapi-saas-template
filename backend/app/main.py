from contextlib import asynccontextmanager

from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference
from starlette.responses import RedirectResponse

from app.api.master_router import router as master_router
from app.core.config.settings import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware.access_log import AccessLogMiddleware
from app.core.middleware.request_context import RequestContextMiddleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app_started")
    try:
        yield
    finally:
        log.info("app_stopped")


def create_app() -> FastAPI:
    configure_logging(
        log_level=settings.LOG_LEVEL,
        log_json=settings.LOG_JSON,
        service_name=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
    )

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AccessLogMiddleware)
    register_exception_handlers(app)
    app.include_router(master_router)

    @app.get("/scalar", include_in_schema=False)
    async def scalar_docs():
        return get_scalar_api_reference(openapi_url=app.openapi_url)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/scalar")

    return app


app = create_app()
