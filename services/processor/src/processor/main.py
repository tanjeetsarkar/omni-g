from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("Processor service starting", extra={"port": settings.http_port})
    yield
    logger.info("Processor service shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Omni-G Processor",
        description="LLM entity extraction, graph persistence, and GraphRAG indexing service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.get("/health", tags=["ops"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "processor"})

    @app.get("/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        return JSONResponse({"status": "ready", "service": "processor"})

    return app


app = create_app()
