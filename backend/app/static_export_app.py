"""Serve a Next.js static export from FastAPI without requiring trailing slashes.

Next ``output: 'export'`` emits flat per-route HTML files (``library.html``,
``workspace.html``, ``ontology/edit.html``, …). Vanilla
``starlette.staticfiles.StaticFiles(html=True)`` only translates directory-style
requests to ``<dir>/index.html`` — it never tries ``<path>.html``. With the
Arango Container Manager / BYOC ingress, requests like
``/_service/.../library`` are stripped to ``/library`` (see
``app.middleware.strip_service_prefix``) and then 404 because no
``library/`` directory exists.

``NextStaticExportApp`` extends ``StaticFiles`` to retry ``<path>.html`` for
extensionless, slashless URLs after the standard lookup misses. Starlette's
existing ``404.html`` fallback inside ``get_response`` is preserved for true
misses, so unknown routes still render the Next 404 page.
"""

from __future__ import annotations

import stat

import anyio
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


def _is_extensionless_clean_url(path: str) -> bool:
    """True for paths like ``library`` or ``ontology/edit`` (no trailing slash, no extension)."""
    if not path:
        return False
    if path.endswith("/"):
        return False
    last_segment = path.rsplit("/", 1)[-1]
    return "." not in last_segment


class NextStaticExportApp(StaticFiles):
    """``StaticFiles`` that also serves ``<path>.html`` for clean Next-export URLs.

    Behaviour:

    1. Delegate to the standard ``StaticFiles.get_response`` first (handles
       static assets, ``index.html`` for directories, ``404.html`` fallback).
    2. If that yields a 404 response (either via ``HTTPException`` or a
       ``FileResponse`` of ``404.html``) AND ``html`` is enabled AND the
       request looks like a clean SPA route (no extension, no trailing slash),
       retry ``<path>.html`` and serve it if present.
    3. Otherwise return the original response (or re-raise) so Starlette's own
       ``404.html`` handling stays intact for true misses.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        original_response: Response | None = None
        try:
            original_response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self.html:
                raise
            if not _is_extensionless_clean_url(path):
                raise
        else:
            if original_response.status_code != 404 or not self.html:
                return original_response
            if not _is_extensionless_clean_url(path):
                return original_response

        html_path = f"{path}.html"
        full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, html_path)
        if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
            return self.file_response(full_path, stat_result, scope)

        if original_response is not None:
            return original_response
        raise HTTPException(status_code=404)
