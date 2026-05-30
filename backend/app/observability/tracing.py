"""OpenTelemetry tracing setup (Stream 7 PR 2 -- E.1, PRD Section 8.5).

This module is the single place tracing is initialised. Call
``setup_tracing(app)`` once from ``main.py`` on startup. Everywhere
else just use ``get_tracer(__name__).start_as_current_span(...)``;
when ``settings.otel_enabled`` is False the OpenTelemetry no-op
provider takes over and those calls cost nothing.

Design notes
------------

* **Default off.** ``settings.otel_enabled`` defaults to False so a
  bare ``pip install`` deployment has zero tracing overhead and
  emits zero outbound traffic. Operators opt in by setting
  ``OTEL_ENABLED=true`` (+ ``OTEL_EXPORTER_OTLP_ENDPOINT=...``).

* **Idempotent.** Calling ``setup_tracing`` twice is a no-op the
  second time. The OpenTelemetry global ``set_tracer_provider`` is
  one-shot per process; we guard against the test suite or a
  hot-reload module getting things into a bad state.

* **FastAPI + HTTPX + logging instrumentation.** These three are
  free wins: ``opentelemetry-instrumentation-fastapi`` wraps every
  request handler with a server span, HTTPX wraps every outbound
  call (LLM, third-party APIs) with a client span linked to the
  current trace, and the logging instrumentor injects
  ``trace_id`` / ``span_id`` into stdlib log records so structlog
  output joins up with traces.

* **No ArangoDB auto-instrumentor.** ``python-arango`` doesn't have
  an OpenTelemetry contrib package on PyPI, so DB calls are
  represented by manual spans in the services that issue them
  (see eg ``temporal._materialize_to_graph`` for the pattern).

* **Sampler.** Parent-based traceid-ratio: a root request's
  sampling decision is made by ratio, and child spans inherit it.
  Keeps a complete trace either fully sampled or fully dropped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ParentBased,
    TraceIdRatioBased,
)
from opentelemetry.trace import Tracer

from app import __version__
from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)

# Module-level flag so ``setup_tracing`` is idempotent even if the
# FastAPI startup hook fires twice (eg under reload) or if tests
# accidentally call it more than once. The OpenTelemetry global
# ``set_tracer_provider`` only honours the first call and warns on
# subsequent ones, which would pollute test output.
_TRACING_INITIALIZED = False


def setup_tracing(app: FastAPI) -> None:
    """Initialise OpenTelemetry tracing for the FastAPI app.

    Safe to call multiple times; only the first invocation has
    effect. When ``settings.otel_enabled`` is False, this still
    runs but installs an ``ALWAYS_OFF`` sampler so no spans are
    recorded -- cheaper than a no-op provider while keeping the
    instrumentation hooks installed (so flipping the env var and
    restarting is the only operator step required to turn
    tracing on without code changes).
    """
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        log.debug("tracing already initialized; skipping re-init")
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": __version__,
            "deployment.environment": settings.app_env,
        }
    )

    if settings.otel_enabled:
        # ParentBased(TraceIdRatioBased(rate)): root spans sampled by
        # ratio, children inherit. Clamps to [0.0, 1.0] in case an
        # operator sets a nonsense value via env.
        rate = max(0.0, min(1.0, settings.otel_trace_sample_rate))
        sampler = ParentBased(root=TraceIdRatioBased(rate))
    else:
        # Tracing is wired but every span is dropped. Cheap; lets the
        # operator flip the env switch without a code deploy.
        sampler = ParentBased(root=ALWAYS_OFF)

    provider = TracerProvider(resource=resource, sampler=sampler)

    if settings.otel_enabled:
        exporter: SpanExporter
        if settings.otel_exporter_otlp_endpoint:
            # OTLP/gRPC -- the standard collector wire protocol.
            # ``insecure=True`` matches the common deployment where
            # the collector is a sidecar / same-VPC service without
            # TLS termination. For TLS, set the endpoint to
            # ``https://...`` and drop ``insecure``.
            exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=settings.otel_exporter_otlp_endpoint.startswith("http://"),
            )
            log.info(
                "tracing enabled -- exporting to OTLP",
                extra={"endpoint": settings.otel_exporter_otlp_endpoint},
            )
        else:
            # No endpoint configured but tracing is on: dump spans
            # to stdout. Useful for local dev / smoke-testing the
            # instrumentation without standing up a collector.
            exporter = ConsoleSpanExporter()
            log.info("tracing enabled -- exporting to console (no OTLP endpoint set)")

        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        log.info("tracing disabled (otel_enabled=False); spans will be dropped")

    trace.set_tracer_provider(provider)

    # FastAPI: every HTTP request becomes a server span with route,
    # method, status code. Names are derived from the route pattern
    # (``/api/v1/ontology/{ontology_id}``) so cardinality is bounded.
    FastAPIInstrumentor.instrument_app(app)

    # HTTPX: every outbound call (LLM providers, third-party APIs)
    # becomes a client span. Links to the current trace, so an
    # extraction request shows its LLM calls as children.
    HTTPXClientInstrumentor().instrument()

    # Logging: inject trace_id / span_id into stdlib log records so
    # ``structlog`` output (which wraps stdlib logging) carries them
    # too. Lets operators jump from a log line to the trace in
    # Jaeger / Tempo.
    LoggingInstrumentor().instrument(set_logging_format=False)

    _TRACING_INITIALIZED = True


def get_tracer(name: str) -> Tracer:
    """Return the tracer for ``name`` (typically ``__name__``).

    Thin re-export so callers don't import ``opentelemetry.trace``
    directly. When ``setup_tracing`` has not run (eg in unit tests
    that don't exercise the FastAPI app), this returns the no-op
    tracer from the API package, which is safe to call.
    """
    return trace.get_tracer(name)
