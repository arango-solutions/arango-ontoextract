from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    curation,
    documents,
    er,
    extraction,
    health,
    metrics,
    notifications,
    ontology,
    orgs,
    ws_curation,
    ws_extraction,
)
from app.api.auth import JWTAuthMiddleware
from app.api.errors import install_error_handlers
from app.api.metrics import PrometheusMiddleware
from app.config import settings
from app.db.client import close_db

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info("starting", env=settings.app_env)
    yield
    close_db()
    log.info("shutdown_complete")


app = FastAPI(
    title="Arango-OntoExtract",
    description="LLM-driven ontology extraction and curation platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)

app.add_middleware(JWTAuthMiddleware)
app.add_middleware(PrometheusMiddleware)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(extraction.router)
app.include_router(ontology.router)
app.include_router(curation.router)
app.include_router(er.router)
app.include_router(orgs.router)
app.include_router(notifications.router)
app.include_router(metrics.router)
app.include_router(ws_extraction.router)
app.include_router(ws_curation.router)
