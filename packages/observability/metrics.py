"""Prometheus metrics (product brief section 23).

Registered against prometheus_client's default global REGISTRY -- the same
choice `logging`'s stdlib module and this project's idempotency/state-machine
modules make (one shared source of truth, not a bespoke registry per
subsystem). Labels are kept to small, bounded sets (status strings, event
type names) deliberately -- a label like merchant_id would give each
merchant its own time series, which is exactly the unbounded-cardinality
mistake real Prometheus deployments get bitten by.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

payment_requests_total = Counter(
    "payguard_payment_requests_total", "Total POST /v1/payments requests that reached create_payment()"
)
payment_success_total = Counter(
    "payguard_payment_success_total", "Payments that authorized successfully (outcome SUCCEEDED)"
)
payment_failure_total = Counter(
    "payguard_payment_failure_total", "Payments that did not authorize successfully", ["reason"]
)
payment_processing_duration_seconds = Histogram(
    "payguard_payment_processing_duration_seconds",
    "Wall-clock time from claiming the idempotency key to returning a response",
)

provider_latency_seconds = Histogram(
    "payguard_provider_latency_seconds", "Provider call latency", ["operation"]
)
provider_timeout_total = Counter(
    "payguard_provider_timeout_total", "Provider calls that returned UNKNOWN (lost response)"
)

idempotency_conflicts_total = Counter(
    "payguard_idempotency_conflicts_total",
    "Idempotency key reused with a different request body (ADR-001)",
)

webhook_events_total = Counter(
    "payguard_webhook_events_total", "Webhook deliveries received (including duplicates)", ["event_type"]
)
webhook_duplicates_total = Counter(
    "payguard_webhook_duplicates_total", "Webhook deliveries that were already-seen duplicates (ADR-006)"
)

refund_total = Counter("payguard_refund_total", "Refund attempts that settled successfully")
refund_failures_total = Counter("payguard_refund_failures_total", "Refund attempts that failed")

outbox_backlog = Gauge("payguard_outbox_backlog", "PENDING outbox_events rows, sampled once per worker poll")

reconciliation_mismatches_total = Counter(
    "payguard_reconciliation_mismatches_total",
    "Reconciliation passes that found a discrepancy needing human review",
    ["result"],
)

rate_limit_rejections_total = Counter(
    "payguard_rate_limit_rejections_total",
    "Requests rejected for exceeding a merchant's rate limit (Phase 16, docs/security.md)",
)


def render_latest() -> tuple[bytes, str]:
    """Returns (body, content_type) ready to hand back as an HTTP response."""
    return generate_latest(), CONTENT_TYPE_LATEST
