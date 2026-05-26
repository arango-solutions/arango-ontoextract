"""Observability module (Stream 7 PR 2 -- E.1).

Centralises OpenTelemetry tracing setup so the call-site code stays
clean: services and routes just call ``trace.get_tracer(__name__)``
and ``start_as_current_span(...)``. When ``settings.otel_enabled``
is False (the default), the OpenTelemetry no-op TracerProvider is
used and those calls are effectively free.

Public surface:

* ``setup_tracing(app)`` -- one-shot init from ``main.py`` on app
  startup. Idempotent.
* ``get_tracer(name)`` -- thin re-export of
  ``opentelemetry.trace.get_tracer`` so callers don't have to import
  the OTel API directly.
"""

from __future__ import annotations

from app.observability.tracing import get_tracer, setup_tracing

__all__ = ["get_tracer", "setup_tracing"]
