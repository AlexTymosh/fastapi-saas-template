"""
------------------------
    Main entry point
------------------------
"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from scalar_fastapi import get_scalar_api_reference

from backend.app.api.master_router import router as master_router

app = FastAPI(
    title="SaaS Template",
    version="0.1.0",
)

app.include_router(master_router)


@app.get("/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(openapi_url=app.openapi_url)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/scalar")
