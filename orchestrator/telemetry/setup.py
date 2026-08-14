"""OpenTelemetry setup: tracing and context propagation.

Key design:
- Trace context propagates through SQS message attributes
- Span links connect retries to previous attempts (one story, not many)
- Head sampling with a fixed low rate for production
- Exporters are OFF for the headline load run
"""

from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.trace import Link, SpanKind, StatusCode

from orchestrator.config import settings


def setup_telemetry() -> None:
    """Initialize OpenTelemetry with sampling and OTLP export."""
    if not settings.otel_enabled:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})

    sampler = ParentBasedTraceIdRatio(float(settings.otel_traces_sampler_arg))

    provider = TracerProvider(resource=resource, sampler=sampler)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception:
        # Exporter not available — continue without export
        pass

    trace.set_tracer_provider(provider)


def get_tracer(name: str = "orchestrator") -> trace.Tracer:
    """Get a named tracer."""
    return trace.get_tracer(name)


def inject_trace_context(carrier: dict[str, str]) -> None:
    """Inject current trace context into a carrier (e.g., SQS message attributes)."""
    inject(carrier)


def extract_trace_context(carrier: dict[str, str]) -> Context:
    """Extract trace context from a carrier (e.g., SQS message attributes)."""
    return extract(carrier)


def create_span_link(carrier: dict[str, str]) -> Link | None:
    """Create a span link from a previous attempt's trace context."""
    ctx = extract(carrier)
    span_ctx = trace.get_current_span(ctx).get_span_context()
    if span_ctx.is_valid:
        return Link(span_ctx, attributes={"link.type": "retry"})
    return None
