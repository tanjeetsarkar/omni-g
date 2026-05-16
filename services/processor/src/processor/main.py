from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("Processor service starting", extra={"port": settings.http_port})
    yield
    logger.info("Processor service shutting down")


class ValidateRequest(BaseModel):
    """Payload received from the Aggregator validation sidecar."""

    source: str
    payload: dict[str, Any]

    @field_validator("source")
    @classmethod
    def source_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source must not be blank")
        return v


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = []


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

    @app.post("/validate", tags=["ops"], response_model=ValidateResponse)
    async def validate(body: ValidateRequest) -> JSONResponse:
        """Schema validation sidecar endpoint called by the Aggregator.

        Validates that the event envelope contains the required top-level
        fields. Full STIX 2.1 validation is deferred to M3.3.
        """
        errors: list[str] = []

        if not body.source:
            errors.append("field 'source' is required")

        if body.payload is None:
            errors.append("field 'payload' is required")

        if errors:
            return JSONResponse(
                status_code=422,
                content={"valid": False, "errors": errors},
            )

        return JSONResponse({"valid": True})

    return app


app = create_app()

