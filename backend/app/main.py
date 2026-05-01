import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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
from app.minimal_login import render_minimal_login_html
from app.static_export_app import NextStaticExportApp

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


_fastapi_kw: dict[str, Any] = {
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
_frontend_dir = resolve_frontend_out_dir(
    __file__,
    override=settings.frontend_static_root or None,
    service_url_path_prefix=settings.service_url_path_prefix,
)
if _frontend_dir is not None:
    log.info("static_frontend_mounted", directory=str(_frontend_dir))
    # NextStaticExportApp adds <path>.html fallback so flat exports
    # (library.html, workspace.html, …) resolve from clean URLs without
    # requiring trailingSlash=true on the Next build. See app/static_export_app.py.
    app.mount(
        "/",
        NextStaticExportApp(directory=str(_frontend_dir), html=True),
        name="static",
    )
else:
    log.warning(
        "frontend_out_not_found - SPA routes (/workspace, /pipeline, ...) will 404; "
        "bundle Next with PACKAGE_INCLUDE_FRONTEND=1, copy frontend/out beside app/, "
        "or set AOE_FRONTEND_OUT_DIR to the static export directory",
        checked_explicit=settings.frontend_static_root or None,
        checked_flat_bundle="<bundle>/frontend/out",
        checked_monorepo="<repo>/frontend/out",
        docker_fallback="/app/static",
    )

    @app.get("/login")
    async def minimal_login_page() -> HTMLResponse:
        """Fallback HTML login when Next static export is not deployed."""
        return HTMLResponse(content=render_minimal_login_html(settings.service_url_path_prefix))
