"""FastAPI application: lifespan (DB pool, models), routers, error handlers."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.admin.documents import router as documents_router
from app.admin.routes import router as admin_router
from app.auth.routes import router as auth_router
from app.config import PRODUCT_NAME, get_settings
from app.db.pool import create_pool
from app.errors import install_error_handlers
from app.ingestion.pipeline import IngestionQueue
from app.ml.embedder import load_embedder

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    app.state.db_pool = await create_pool(settings.database_url)
    # System 1 models load once here. The reranker, NLI and classifier join in tasks 03-04.
    app.state.embedder = await asyncio.to_thread(
        load_embedder,
        settings.model_backend,
        settings.embedding_model,
        settings.embedding_dim,
        settings.embed_batch_size,
    )
    app.state.ingestion = IngestionQueue(app.state.db_pool, app.state.embedder, settings)
    resumed = await app.state.ingestion.requeue_interrupted()
    if resumed:
        log.info("resumed processing for %d document(s)", resumed)
    try:
        yield
    finally:
        await app.state.ingestion.cancel_all()
        await app.state.db_pool.close()


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "unavailable"]


def create_app() -> FastAPI:
    app = FastAPI(title=f"{PRODUCT_NAME} API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(documents_router)

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
