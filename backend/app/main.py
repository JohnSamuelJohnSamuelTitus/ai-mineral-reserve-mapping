"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import Base
from app.db.seed import seed_default_data_sources
from app.db.session import get_engine, get_session_factory

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = get_engine()
    if settings.is_sqlite:
        Base.metadata.create_all(bind=engine)
    with get_session_factory()() as db:
        inserted = seed_default_data_sources(db)
        if inserted:
            logger.info("Seeded %d default data_sources", inserted)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Mineral Reserve Mapping Assistant API",
        version="0.2.0",
        description=(
            "Geospatial data infrastructure and ingestion API. "
            "Supports prospectivity data preparation only; does NOT establish proven mineral reserves."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()

