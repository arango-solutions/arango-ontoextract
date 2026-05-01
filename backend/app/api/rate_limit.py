"""Redis-backed sliding window rate limiter middleware.

Per-org limits:
  - standard tier: 100 requests/minute
  - premium tier: 1000 requests/minute

Uses a Redis sorted-set sliding window: each request adds a timestamped entry,
expired entries are pruned, and the remaining count is compared against the limit.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.config import settings

log = logging.getLogger(__name__)

TIER_LIMITS: dict[str, int] = {
    "standard": 100,
    "premium": 1000,
}

WINDOW_SECONDS = 60

# ``from_url`` does not connect; first ``execute()`` on a pipeline did — noisy tracebacks
# in k8s without Redis. We ``ping()`` once, cache the client, and back off after failures.
_redis_client: Any | None = None
_redis_unavailable_until: float = 0.0
_REDIS_BACKOFF_SECONDS = 60.0


def _get_redis():
    """Lazy import, validate with ``ping``, cache client. Returns None if unavailable."""
    global _redis_client, _redis_unavailable_until

    now = time.time()
    if now < _redis_unavailable_until:
        return None

    try:
        import redis
        from redis.exceptions import RedisError
    except Exception:
        log.warning("redis_import_failed_rate_limit_pass_through")
        _redis_unavailable_until = now + _REDIS_BACKOFF_SECONDS
        return None

    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except RedisError:
            with contextlib.suppress(Exception):
                _redis_client.close()
            _redis_client = None
            _redis_unavailable_until = now + _REDIS_BACKOFF_SECONDS

    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.ping()
        _redis_client = client
        _redis_unavailable_until = 0.0
        return client
    except Exception as exc:
        _redis_unavailable_until = now + _REDIS_BACKOFF_SECONDS
        log.warning(
            "redis_unavailable_rate_limit_pass_through "
            "(set REDIS_URL to your Redis service, or RATE_LIMIT_ENABLED=false): %s",
            exc,
        )
        return None


def _org_id_from_request(request: Request) -> str:
    """Extract org identifier for rate-limit bucketing.

    Priority:
      1. ``X-Org-Id`` header (set by auth middleware / API gateway)
      2. ``org_id`` query parameter
      3. Client IP as fallback
    """
    org = request.headers.get("X-Org-Id")
    if org:
        return org
    org = request.query_params.get("org_id")
    if org:
        return org
    client = request.client
    return client.host if client else "unknown"


def _tier_from_request(request: Request) -> str:
    """Resolve the caller's tier for limit selection.

    Falls back to ``settings.rate_limit_default_tier``.
    """
    tier = request.headers.get("X-Org-Tier")
    if tier and tier in TIER_LIMITS:
        return tier
    return settings.rate_limit_default_tier


def check_rate_limit(
    org_id: str,
    tier: str,
    *,
    redis_client: Any | None = None,
    now: float | None = None,
) -> tuple[bool, int, int, float]:
    """Sliding-window rate-limit check.

    Returns ``(allowed, remaining, limit, retry_after_seconds)``.
    """
    if now is None:
        now = time.time()

    limit = TIER_LIMITS.get(tier, settings.rate_limit_default)
    window_start = now - WINDOW_SECONDS

    r = redis_client or _get_redis()
    if r is None:
        return True, limit, limit, 0.0

    key = f"ratelimit:{org_id}"

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {f"{now}": now})
        pipe.zcard(key)
        pipe.expire(key, WINDOW_SECONDS + 1)
        results = pipe.execute()

        current_count: int = results[2]
        remaining = max(0, limit - current_count)
        allowed = current_count <= limit

        if not allowed:
            oldest_in_window = r.zrange(key, 0, 0, withscores=True)
            if oldest_in_window:
                retry_after = oldest_in_window[0][1] + WINDOW_SECONDS - now
                retry_after = max(0.0, retry_after)
            else:
                retry_after = float(WINDOW_SECONDS)
        else:
            retry_after = 0.0

        return allowed, remaining, limit, retry_after
    except Exception as exc:
        # Stale pooled connection or Redis died mid-request — allow traffic; refresh client.
        global _redis_client, _redis_unavailable_until

        log.warning("redis_pipeline_failed_rate_limit_pass_through: %s", exc)
        try:
            if _redis_client is not None:
                _redis_client.close()
        except Exception:
            pass
        _redis_client = None
        _redis_unavailable_until = time.time() + _REDIS_BACKOFF_SECONDS
        return True, limit, limit, 0.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces per-org sliding-window rate limits."""

    EXEMPT_PATHS: frozenset[str] = frozenset(
        {"/health", "/ready", "/docs", "/openapi.json", "/redoc", "/login"}
    )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if (
            path in self.EXEMPT_PATHS
            or path.startswith("/_next/")
            or path
            in (
                "/favicon.svg",
                "/favicon.ico",
            )
        ):
            return await call_next(request)

        org_id = _org_id_from_request(request)
        tier = _tier_from_request(request)

        try:
            allowed, remaining, limit, retry_after = check_rate_limit(org_id, tier)
        except Exception:
            log.warning("rate_limit_check_failed", exc_info=True)
            return await call_next(request)

        if not allowed:
            retry_after_int = max(1, int(retry_after) + 1)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": retry_after_int,
                },
                headers={
                    "Retry-After": str(retry_after_int),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after_int),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
