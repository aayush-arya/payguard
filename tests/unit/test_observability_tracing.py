"""Unit tests for the tracing setup, using OpenTelemetry's own
InMemorySpanExporter -- proves spans are actually created and correctly
nested/correlated, not just that the API can be called without error."""

from observability.tracing import configure_tracing, get_tracer
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_span_is_recorded_with_its_name_and_attributes():
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)
    tracer = get_tracer("test.tracer")

    with tracer.start_as_current_span("demo.span") as span:
        span.set_attribute("payment.id", "pay_123")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "demo.span"
    assert spans[0].attributes["payment.id"] == "pay_123"


def test_nested_spans_share_one_trace_id_and_record_parentage():
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)
    tracer = get_tracer("test.tracer")

    with tracer.start_as_current_span("outer") as outer_span:
        with tracer.start_as_current_span("inner") as inner_span:
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    trace_ids = {s.context.trace_id for s in spans}
    assert len(trace_ids) == 1, "nested spans must belong to the same trace"

    inner = next(s for s in spans if s.name == "inner")
    assert inner.parent is not None
    assert inner.parent.span_id == outer_span.get_span_context().span_id
    assert inner_span.get_span_context().trace_id == outer_span.get_span_context().trace_id


def test_sibling_operations_get_independent_traces():
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)
    tracer = get_tracer("test.tracer")

    with tracer.start_as_current_span("request.one"):
        pass
    with tracer.start_as_current_span("request.two"):
        pass

    spans = exporter.get_finished_spans()
    trace_ids = {s.context.trace_id for s in spans}
    assert len(trace_ids) == 2, "unrelated top-level operations must not share a trace"
