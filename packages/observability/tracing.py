"""Lightweight distributed tracing (product brief section 23), via
OpenTelemetry's API directly -- spans are created by hand at the operations
that matter (payment create/capture/refund, webhook apply, reconciliation),
not through blanket auto-instrumentation. That's a deliberate choice: a
hand-placed span at "authorize a payment" is more informative than an
auto-generated one at "handle an HTTP request", and it's what actually
answers "where did this payment's time go."

No collector (Jaeger/Tempo) is wired up yet -- that's deferred to Phase 17
alongside containerizing the API/worker themselves, so the observability
stack gets built once, coherently, rather than half-configured against a
host-run process now and reworked later (docs/observability.md). Locally,
spans export to a ConsoleSpanExporter; tests substitute an
InMemorySpanExporter to assert on what was actually recorded.

`get_tracer()` reads from a module-level provider reference, not from
`opentelemetry.trace`'s global registry -- the SDK only allows
`set_tracer_provider()` to succeed once per process (later calls are
silently ignored with a warning), which would make `configure_tracing()`
unusable for per-test isolation. We still attempt to set the global (best
effort, first call wins) for compatibility with any third-party code that
calls the raw OTel API directly; nothing in this codebase does that --
everything goes through `get_tracer()` below.

`get_tracer()` returns a lazy proxy, not a Tracer bound to whatever provider
happened to be current at call time. This matters because several modules
(apps/api/main.py, packages/payments/service.py, ...) call `get_tracer()`
once at *import* time and cache the result in a module-level `_tracer` --
if that returned a real `Tracer` eagerly bound to "the provider that existed
when this module first imported", a later `configure_tracing()` call (e.g.
a test installing an InMemorySpanExporter) would have no effect on spans
those modules create. The proxy re-resolves the current provider on every
`start_as_current_span()` call instead, so reconfiguration always takes
effect immediately everywhere, with zero changes needed at any call site.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor, SpanExporter

_SERVICE_NAME = "payguard"
_provider: TracerProvider | None = None


def configure_tracing(exporter: SpanExporter | None = None) -> TracerProvider:
    """Creates a fresh TracerProvider that `get_tracer()`'s lazy proxies
    will pick up on their next call. Safe to call more than once (e.g. once
    per test)."""
    global _provider
    _provider = TracerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))
    _provider.add_span_processor(SimpleSpanProcessor(exporter or ConsoleSpanExporter()))
    try:
        trace.set_tracer_provider(_provider)
    except Exception:
        pass
    return _provider


class _LazyTracer:
    """Delegates every call to whatever `get_tracer(name)` currently
    resolves to -- see the module docstring for why this can't just be a
    plain cached `Tracer` instance."""

    def __init__(self, name: str) -> None:
        self._name = name

    def start_as_current_span(self, *args: Any, **kwargs: Any):
        return _resolve(self._name).start_as_current_span(*args, **kwargs)


def _resolve(name: str) -> trace.Tracer:
    if _provider is None:
        configure_tracing()
    assert _provider is not None
    return _provider.get_tracer(name)


def get_tracer(name: str) -> _LazyTracer:
    return _LazyTracer(name)
