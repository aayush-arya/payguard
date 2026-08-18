# Observability (Phase 12)

Status: implemented. Three independent, complementary signals — structured
logs, metrics, traces — wired directly into the code paths that matter, not
bolted on as generic middleware.

## Structured logging (`packages/observability/logging.py`)

Every log line is a single JSON object (`JSONFormatter`), not free-text —
built to be machine-parsed by a log aggregator, not eyeballed in a terminal.
Correlation fields (`request_id`, `merchant_id`, `payment_id`,
`provider_transaction_id`) are carried via `contextvars.ContextVar`, not
passed as explicit arguments through every function call between the HTTP
layer and a service three modules deep. `bind_context()` is a context
manager: fields are set on entry and *restored* (not just cleared) on exit,
so nested `bind_context()` calls (an outer request-level bind, an inner
payment-level bind) compose correctly instead of one clobbering the other
permanently.

The alternative — threading a `request_id: str` parameter through every
service function's signature — was rejected: it would leak an HTTP-layer
concern (correlation) into packages that have no other reason to know an
HTTP request exists (`packages/ledger`, `packages/reconciliation`), and every
new correlation field would mean touching every call site between the API
boundary and wherever it's needed.

## Metrics (`packages/observability/metrics.py`)

Thirteen Prometheus metrics (product brief section 23), all prefixed
`payguard_`, covering payment volume/outcome, provider latency and timeouts,
idempotency conflicts, webhook volume/duplicates, refund outcomes, outbox
backlog, and reconciliation mismatches. `GET /metrics` (`apps/api/main.py`)
serves them in standard Prometheus text exposition format via
`prometheus_client`'s own registry and encoder — no hand-rolled
serialization.

Counters are incremented at the exact point an outcome is known (e.g.
`payment_failure_total.labels(reason="declined")` right where the provider's
`DECLINED` outcome is handled in `packages/payments/service.py`), not
inferred after the fact from log lines or database state. `outbox_backlog`
is the one gauge: the worker (`apps/worker/main.py`) sets it from a `COUNT`
query at the start of every poll loop iteration, so it reflects current
state rather than an event count.

## Tracing (`packages/observability/tracing.py`)

Spans are created by hand at the operations that matter — `provider.authorize`,
`provider.capture`, `provider.refund`,
`provider.get_payment_status_by_idempotency_key`, and one `http.request` span
per inbound request — via OpenTelemetry's API directly, not blanket
auto-instrumentation. A hand-placed span at "authorize a payment" answers
"where did this payment's time go" far more usefully than an
auto-generated one at "handle an HTTP request" ever could.

No collector (Jaeger/Tempo) is wired up yet — locally, spans export to a
`ConsoleSpanExporter`. Wiring a real collector is deferred to Phase 17
alongside containerizing the API/worker themselves, so the tracing stack
gets built out once, coherently, rather than half-configured against a
host-run process now and reworked later.

### The two OpenTelemetry SDK gotchas this design works around

1. **`trace.set_tracer_provider()` succeeds exactly once per process.** OTel's
   global registry is deliberately write-once — a second call is silently
   ignored (with a warning). That's fine for a real long-lived process, but
   it makes the global registry unusable for per-test isolation: a test that
   wants its own `InMemorySpanExporter` can't just call
   `configure_tracing()` and expect it to take effect if an earlier test (or
   `apps/api/main.py` at import time) already claimed the global provider.
   `get_tracer()` therefore reads from a module-level `_provider` reference
   inside `packages/observability/tracing.py`, not from
   `opentelemetry.trace`'s global registry. (It still best-effort calls
   `set_tracer_provider()` too, for compatibility with any third-party code
   that reads the raw OTel API directly — nothing in this codebase does.)

2. **Modules cache `get_tracer()`'s return value at import time.**
   `packages/payments/service.py` and others do
   `_tracer = get_tracer("payguard.payments")` once, at module scope. If
   `get_tracer()` returned a real `Tracer` object eagerly bound to whichever
   provider existed at that moment, a later `configure_tracing()` call (a
   test installing its own exporter) would have zero effect on spans those
   modules create — they'd keep reporting to the stale provider forever.
   `get_tracer()` instead returns a `_LazyTracer` proxy that re-resolves the
   *current* `_provider` on every `start_as_current_span()` call, so
   reconfiguration takes effect immediately everywhere, with no changes
   needed at any call site.

Both gotchas were caught by writing `tests/unit/test_observability_tracing.py`
*before* trusting the wiring — the first version of `tracing.py` (a thin
wrapper directly over `opentelemetry.trace.get_tracer()`) imported cleanly
and looked correct, but two of the three tests failed with zero spans
recorded, because the test's fresh `InMemorySpanExporter` was never actually
receiving anything from the already-claimed global provider.

## Where it plugs in

`apps/api/main.py` configures logging and tracing at module load, and wraps
every request in `_request_id_middleware`: it generates a `req_<hex>` ID,
binds it into the logging context, opens an `http.request` span, and echoes
it back as the `X-Request-Id` response header — the same ID appears in every
log line, every child span, and the error envelope
(`{"error": {..., "request_id": ...}}`) for that request, without any
downstream package importing anything request-scoped.
`apps/api/dependencies.py`'s `get_current_merchant` adds `merchant_id` to the
context once authentication succeeds. `packages/payments/service.py` adds
`payment_id` as soon as a payment row exists (or is looked up), so even the
very first log lines for a new payment — before its ID would otherwise be
knowable to a caller — carry it. `apps/worker/main.py` mirrors the same
`configure_logging()`/`configure_tracing()` setup for the standalone worker
process.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | JSON log formatting, context fields present/absent/restored across nesting, unknown-field rejection | `tests/unit/test_observability_logging.py` |
| Unit | Every named metric increments/observes correctly; `/metrics`-shaped output contains all 13 metric families | `tests/unit/test_observability_metrics.py` |
| Unit | Spans recorded with correct name/attributes; nested spans share a trace and record parent/child; unrelated top-level spans get independent traces | `tests/unit/test_observability_tracing.py` |
| Integration | `GET /metrics` reachable and well-formed through the real API; a real `POST /v1/payments` call moves real counters (including the `declined` and idempotency-conflict label paths); a real `provider.authorize` span is emitted by `create_payment()`; every response carries a request ID that also appears in the error envelope | `tests/integration/test_observability.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first).
