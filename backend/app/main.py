import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    admin,
    auth,
    curation,
    documents,
    er,
    extraction,
    health,
    metrics,
    notifications,
    ontology,
    orgs,
    quality,
    ws_curation,
    ws_extraction,
)
from app.api.auth import JWTAuthMiddleware
from app.api.errors import install_error_handlers
from app.api.metrics import PrometheusMiddleware
from app.api.rate_limit import RateLimitMiddleware
from app.config import settings
from app.db.client import close_db
from app.frontend_static import resolve_frontend_out_dir
from app.middleware.strip_service_prefix import StripServicePrefixMiddleware

logging.basicConfig(
    level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
    format="%(levelname)-5s %(name)s: %(message)s",
)

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


_fastapi_kw: dict = {
    "title": "Arango-OntoExtract",
    "description": "LLM-driven ontology extraction and curation platform",
    "version": "0.1.0",
    "lifespan": lifespan,
}
if settings.service_url_path_prefix:
    _fastapi_kw["root_path"] = settings.service_url_path_prefix

app = FastAPI(**_fastapi_kw)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

install_error_handlers(app)

app.add_middleware(JWTAuthMiddleware)
app.add_middleware(PrometheusMiddleware)

if settings.rate_limit_enabled:
    app.add_middleware(RateLimitMiddleware)

if settings.service_url_path_prefix:
    # Outermost: strip public prefix before routing (see StripServicePrefixMiddleware).
    app.add_middleware(StripServicePrefixMiddleware, prefix=settings.service_url_path_prefix)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(documents.router)
app.include_router(extraction.router)
app.include_router(admin.router)
app.include_router(ontology.router)
app.include_router(curation.router)
app.include_router(er.router)
app.include_router(orgs.router)
app.include_router(notifications.router)
app.include_router(metrics.router)
app.include_router(quality.router)
app.include_router(ws_extraction.router)
app.include_router(ws_curation.router)

# Serve static frontend files if they exist (Next.js static export → frontend/out/)
_frontend_dir = resolve_frontend_out_dir(__file__)
if _frontend_dir is not None:
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="static")
else:
    log.warning(
        "frontend_out_not_found",
        checked_flat_bundle="<bundle>/frontend/out",
        checked_monorepo="<repo>/frontend/out",
        docker_fallback="/app/static",
    )


