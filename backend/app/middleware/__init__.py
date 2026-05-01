"""ASGI middleware."""

from app.middleware.strip_service_prefix import StripServicePrefixMiddleware

__all__ = ["StripServicePrefixMiddleware"]
