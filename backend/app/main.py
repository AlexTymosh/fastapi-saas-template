"""
------------------------
    Main entry point
------------------------
"""

from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference
from starlette.responses import RedirectResponse

from app.api.master_router import router as master_router
from app.core.errors import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="SaaS Template",
        version="0.1.0",
    )
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
