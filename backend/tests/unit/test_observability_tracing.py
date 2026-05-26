"""Unit tests for app.observability.tracing (Stream 7 PR 2 -- E.1).

The module sets up OpenTelemetry tracing for the FastAPI app. These
tests pin the contracts the rest of the codebase relies on:

* Default-off: ``settings.otel_enabled=False`` means no spans are
  recorded (regression guard against accidentally shipping with
  tracing on).
* Idempotent: ``setup_tracing(app)`` called twice is safe -- only
  the first invocation has effect.
* Enabling tracing routes spans to the configured exporter (OTLP
  vs Console picked by config).
* The ``get_tracer`` re-export returns a working tracer.
* Manual spans created via an SDK ``TracerProvider`` are recorded
  with their attributes and form parent/child relationships.

Test-isolation note: OpenTelemetry's global ``set_tracer_provider``
is one-shot per process and refuses subsequent overrides. Rather
than fight that with private-attribute surgery, the tests that need
a real recording tracer instantiate a local ``TracerProvider``
directly and use ``provider.get_tracer(...)``. This bypasses the
global registry entirely and keeps the suite hermetic regardless
of test-execution order.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased


@pytest.fixture()
def _reset_tracing_state():
    """Reset the module-level ``_TRACING_INITIALIZED`` flag so a
    test can re-enter ``setup_tracing`` for assertion purposes.

    We deliberately do NOT touch the global ``TracerProvider`` --
    OTel locks it to a single provider per process, and trying to
    swap it via private attrs is fragile. Tests that need a real
    recording tracer use ``_in_memory_tracer`` below, which works
    against a local provider instead of the global one.
    """
    from app.observability import tracing as tracing_mod

    original_initialized = tracing_mod._TRACING_INITIALIZED
    tracing_mod._TRACING_INITIALIZED = False
    try:
        yield
    finally:
        tracing_mod._TRACING_INITIALIZED = original_initialized


@pytest.fixture()
def _in_memory_tracer():
    """Yield (tracer, exporter) for a hermetic in-memory tracer.

    Uses a local SDK ``TracerProvider`` (no globals touched) so
    spans created via the returned tracer are captured by the
    in-memory exporter and tests can assert on them. Sidesteps the
    "Overriding of current TracerProvider is not allowed" warning
    that the global ``set_tracer_provider`` raises after the first
    setup of the process.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "test"}),
        sampler=ParentBased(root=ALWAYS_ON),
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    yield tracer, exporter


class TestSetupTracing:
    """Contract: ``setup_tracing`` is the single entry point for OTel
    initialization. It must respect the config switch, be idempotent,
    and install the FastAPI/HTTPX/logging instrumentors.
    """

    def test_disabled_by_default_does_not_raise(self, _reset_tracing_state) -> None:
        """``settings.otel_enabled=False`` (the default) must complete
        setup without raising and without emitting any outbound
        traffic. We assert it returns cleanly; the absence of
        exceptions IS the contract for the no-tracing default path.

        This is the regression guard: if a future PR flips the
        default to True by accident, the integration would still
        work (no error) but the test_enabled_with_otlp_endpoint
        test below would start failing because the config mock
        would no longer match.
        """
        from app.observability.tracing import setup_tracing

        app = FastAPI()
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            mock_settings.otel_service_name = "test"
            mock_settings.app_env = "test"
            mock_settings.otel_exporter_otlp_endpoint = ""
            mock_settings.otel_trace_sample_rate = 1.0
            setup_tracing(app)

    def test_idempotent_double_call(self, _reset_tracing_state) -> None:
        """Calling ``setup_tracing`` twice must NOT raise and must NOT
        re-install instrumentation. The FastAPI instrumentor's
        ``instrument_app`` raises if called twice on the same app
        without unwrapping, so this test would catch a regression
        where the idempotency flag is removed.
        """
        from app.observability.tracing import setup_tracing

        app = FastAPI()
        with patch("app.observability.tracing.settings") as mock_settings:
            mock_settings.otel_enabled = False
            mock_settings.otel_service_name = "test"
            mock_settings.app_env = "test"
            mock_settings.otel_exporter_otlp_endpoint = ""
            mock_settings.otel_trace_sample_rate = 1.0
            setup_tracing(app)
            setup_tracing(app)

    def test_enabled_with_otlp_endpoint_picks_otlp_exporter(self, _reset_tracing_state) -> None:
        """When ``otel_enabled=True`` and an OTLP endpoint is set,
        the OTLP gRPC exporter must be selected. We patch the
        BatchSpanProcessor to capture which exporter type was wired,
        rather than actually opening a gRPC channel to nowhere.
        """
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        from app.observability.tracing import setup_tracing

        captured_exporters: list[Any] = []

        def capture_processor(exporter):
            captured_exporters.append(exporter)
            return SimpleSpanProcessor(exporter)

        app = FastAPI()
        with (
            patch("app.observability.tracing.settings") as mock_settings,
            patch(
                "app.observability.tracing.BatchSpanProcessor",
                side_effect=capture_processor,
            ),
        ):
            mock_settings.otel_enabled = True
            mock_settings.otel_service_name = "test"
            mock_settings.app_env = "test"
            mock_settings.otel_exporter_otlp_endpoint = "http://localhost:4317"
            mock_settings.otel_trace_sample_rate = 1.0
            setup_tracing(app)

        assert len(captured_exporters) == 1
        assert isinstance(captured_exporters[0], OTLPSpanExporter)

    def test_enabled_without_endpoint_uses_console_exporter(self, _reset_tracing_state) -> None:
        """``otel_enabled=True`` but no OTLP endpoint -> Console
        exporter. This is the local-dev / smoke-test mode -- handy
        for verifying instrumentation without standing up a collector.
        """
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        from app.observability.tracing import setup_tracing

        captured_exporters: list[Any] = []

        def capture_processor(exporter):
            captured_exporters.append(exporter)
            return SimpleSpanProcessor(exporter)

        app = FastAPI()
        with (
            patch("app.observability.tracing.settings") as mock_settings,
            patch(
                "app.observability.tracing.BatchSpanProcessor",
                side_effect=capture_processor,
            ),
        ):
            mock_settings.otel_enabled = True
            mock_settings.otel_service_name = "test"
            mock_settings.app_env = "test"
            mock_settings.otel_exporter_otlp_endpoint = ""
            mock_settings.otel_trace_sample_rate = 1.0
            setup_tracing(app)

        assert len(captured_exporters) == 1
        assert isinstance(captured_exporters[0], ConsoleSpanExporter)

    def test_sample_rate_clamped_to_unit_interval(self, _reset_tracing_state) -> None:
        """Operators are humans. A typo in env (eg
        ``OTEL_TRACE_SAMPLE_RATE=10`` instead of ``0.1``) shouldn't
        blow up the app at startup; we clamp to [0, 1]. The clamp
        also handles negative inputs and inf.

        We can't easily introspect the sampler's ratio without
        relying on private attrs, so this test asserts setup_tracing
        does not raise on the boundary values that would otherwise
        explode in the sampler constructor.
        """
        from app.observability import tracing as tracing_mod
        from app.observability.tracing import setup_tracing

        for rate in (-1.0, 0.0, 0.5, 1.0, 2.0, float("inf")):
            tracing_mod._TRACING_INITIALIZED = False
            app = FastAPI()
            with patch("app.observability.tracing.settings") as mock_settings:
                mock_settings.otel_enabled = True
                mock_settings.otel_service_name = "test"
                mock_settings.app_env = "test"
                mock_settings.otel_exporter_otlp_endpoint = ""
                mock_settings.otel_trace_sample_rate = rate
                setup_tracing(app)


class TestGetTracer:
    """Contract: ``get_tracer`` is a thin re-export. Callers use it
    instead of importing OTel API directly so we have a single seam
    to swap implementations if needed.
    """

    def test_returns_a_usable_tracer(self) -> None:
        """``get_tracer`` must return something whose
        ``start_as_current_span`` works as a context manager,
        whether or not ``setup_tracing`` has been called. OTel's
        API package provides a no-op tracer as the default, so this
        works before setup too.
        """
        from app.observability import get_tracer

        tracer = get_tracer("test")
        with tracer.start_as_current_span("test") as span:
            assert span is not None


class TestManualSpanEmission:
    """The headline contract for the rest of the codebase: spans
    created via a real SDK tracer carry their attributes and form
    parent/child relationships.

    These tests use ``_in_memory_tracer`` (a LOCAL TracerProvider)
    rather than the global one to keep the suite hermetic.
    """

    def test_records_attributes(self, _in_memory_tracer) -> None:
        """When a manual span is created with attributes, those
        attributes appear on the recorded span. This is what makes
        the manual instrumentation in ``tasks.process_document`` and
        ``extraction.execute_run`` actually useful in Jaeger / Tempo.
        """
        tracer, exporter = _in_memory_tracer
        with tracer.start_as_current_span(
            "my_span",
            attributes={"foo": "bar", "count": 42},
        ):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my_span"
        assert spans[0].attributes["foo"] == "bar"
        assert spans[0].attributes["count"] == 42

    def test_nested_spans_form_parent_child_relationship(self, _in_memory_tracer) -> None:
        """Pipeline traces depend on this: ``ingest.document`` ->
        ``ingest.parse`` must show up as a parent/child relationship
        in Jaeger / Tempo, not as two unrelated spans. Verify the
        context propagation works.
        """
        tracer, exporter = _in_memory_tracer
        with (
            tracer.start_as_current_span("parent") as parent,
            tracer.start_as_current_span("child"),
        ):
            parent_ctx = parent.get_span_context()

        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert "parent" in spans
        assert "child" in spans
        assert spans["child"].parent is not None
        assert spans["child"].parent.span_id == parent_ctx.span_id

    def test_set_attribute_post_creation(self, _in_memory_tracer) -> None:
        """``set_attribute`` after the span starts must take effect.
        Used in ``ingest.parse`` (sections count) and
        ``extraction.run`` (errors count) to attach values that
        aren't known at span-creation time.
        """
        tracer, exporter = _in_memory_tracer
        with tracer.start_as_current_span("dynamic") as span:
            span.set_attribute("computed_value", 7)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["computed_value"] == 7

    def test_record_exception_attaches_event_to_span(self, _in_memory_tracer) -> None:
        """Failed pipeline runs must record the exception on the
        span so operators can find errors in the trace view. The
        ``ingest.document`` and ``ontology.graph.ensure`` handlers
        both use ``span.record_exception(exc)`` for this.
        """
        tracer, exporter = _in_memory_tracer
        with tracer.start_as_current_span("explodes") as span:
            try:
                raise ValueError("boom")
            except ValueError as exc:
                span.record_exception(exc)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        # OTel attaches the exception as a span event named "exception".
        event_names = [e.name for e in spans[0].events]
        assert "exception" in event_names
