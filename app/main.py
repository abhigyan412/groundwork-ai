"""FastAPI application: lifespan (DB pool, models), routers, error handlers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.admin.routes import router as admin_router
from app.auth.routes import router as auth_router
from app.config import PRODUCT_NAME, get_settings
from app.db.pool import create_pool
from app.errors import install_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    app.state.db_pool = await create_pool(settings.database_url)
    # System 1 models (embedder, reranker, NLI, classifier) load here once, from task 02 on.
    app.state.models = {}
    try:
        yield
    finally:
        await app.state.db_pool.close()


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "unavailable"]


def create_app() -> FastAPI:
    app = FastAPI(title=f"{PRODUCT_NAME} API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/health", tags=["ops"], responses={503: {"model": HealthResponse}})
    async def health(request: Request) -> HealthResponse:
        try:
            async with request.app.state.db_pool.acquire(timeout=2) as conn:
                await conn.fetchval("SELECT 1")
        except Exception:
            body = HealthResponse(status="degraded", db="unavailable")
            return JSONResponse(status_code=503, content=body.model_dump())  # type: ignore[return-value]
        return HealthResponse(status="ok", db="ok")

    return app


app = create_app()
