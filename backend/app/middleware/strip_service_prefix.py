"""Strip a fixed public URL prefix before routing (Arango pilot / Container Manager).

Traffic may arrive as ``GET /_service/uds/_db/<db>/<service>/health`` while route
handlers stay mounted at ``/health``. This middleware removes the configured
prefix so existing routers match.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


def normalize_service_url_path_prefix(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if not s.startswith("/"):
        s = "/" + s
    return s.rstrip("/")


def stripped_path_if_under_prefix(path: str, prefix: str) -> str | None:
    """If ``path`` equals or lives under ``prefix``, return the remainder; else ``None``.

    ``prefix`` must be normalized (no trailing slash except empty).
    """
    if not prefix:
        return None
    if path == prefix:
        return "/"
    if path.startswith(prefix + "/"):
        return path[len(prefix) :]
    return None


class StripServicePrefixMiddleware:
    """ASGI middleware: strip ``prefix`` from HTTP and WebSocket paths."""

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = normalize_service_url_path_prefix(prefix)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        prefix = self.prefix
        if not prefix:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        new_path = stripped_path_if_under_prefix(path, prefix)
        if new_path is None:
            await self.app(scope, receive, send)
            return

        scope = dict(scope)
        scope["path"] = new_path
        prev_root = scope.get("root_path") or ""
        scope["root_path"] = prev_root + prefix
        await self.app(scope, receive, send)
