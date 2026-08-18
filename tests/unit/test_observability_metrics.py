"""Unit tests for the Prometheus metric definitions (product brief section
23) -- that every named metric exists, increments correctly, and appears in
the rendered /metrics output. Reads Counter/Gauge internals directly
(`._value.get()`) for precise before/after assertions; prometheus_client
doesn't expose a public getter, and this is a read-only, well-established
pattern for testing metrics without needing to scrape and re-parse text.
"""

from observability.metrics import (
    idempotency_conflicts_total,
    outbox_backlog,
    payment_failure_total,
    payment_processing_duration_seconds,
    payment_requests_total,
    payment_success_total,
    provider_latency_seconds,
    provider_timeout_total,
    reconciliation_mismatches_total,
    refund_failures_total,
    refund_total,
    render_latest,
    webhook_duplicates_total,
    webhook_events_total,
)


def test_payment_requests_total_increments():
    before = payment_requests_total._value.get()
    payment_requests_total.inc()
    assert payment_requests_total._value.get() == before + 1


def test_payment_success_total_increments():
    before = payment_success_total._value.get()
    payment_success_total.inc()
    assert payment_success_total._value.get() == before + 1


def test_payment_failure_total_is_labeled_by_reason():
    before = payment_failure_total.labels(reason="declined")._value.get()
    payment_failure_total.labels(reason="declined").inc()
    assert payment_failure_total.labels(reason="declined")._value.get() == before + 1


def test_provider_timeout_total_increments():
    before = provider_timeout_total._value.get()
    provider_timeout_total.inc()
    assert provider_timeout_total._value.get() == before + 1


def test_idempotency_conflicts_total_increments():
    before = idempotency_conflicts_total._value.get()
    idempotency_conflicts_total.inc()
    assert idempotency_conflicts_total._value.get() == before + 1


def test_webhook_events_total_is_labeled_by_event_type():
    before = webhook_events_total.labels(event_type="payment.succeeded")._value.get()
    webhook_events_total.labels(event_type="payment.succeeded").inc()
    assert webhook_events_total.labels(event_type="payment.succeeded")._value.get() == before + 1


def test_webhook_duplicates_total_increments():
    before = webhook_duplicates_total._value.get()
    webhook_duplicates_total.inc()
    assert webhook_duplicates_total._value.get() == before + 1


def test_refund_total_and_refund_failures_total_are_independent():
    before_ok = refund_total._value.get()
    before_fail = refund_failures_total._value.get()
    refund_total.inc()
    assert refund_total._value.get() == before_ok + 1
    assert refund_failures_total._value.get() == before_fail


def test_outbox_backlog_gauge_reflects_the_last_value_set():
    outbox_backlog.set(7)
    assert outbox_backlog._value.get() == 7
    outbox_backlog.set(0)
    assert outbox_backlog._value.get() == 0


def test_reconciliation_mismatches_total_is_labeled_by_result():
    before = reconciliation_mismatches_total.labels(result="AMOUNT_MISMATCH")._value.get()
    reconciliation_mismatches_total.labels(result="AMOUNT_MISMATCH").inc()
    assert reconciliation_mismatches_total.labels(result="AMOUNT_MISMATCH")._value.get() == before + 1


def test_histograms_accept_observations():
    payment_processing_duration_seconds.observe(0.5)
    provider_latency_seconds.labels(operation="authorize").observe(0.2)  # must not raise


def test_render_latest_returns_prometheus_text_format_with_every_named_metric():
    body, content_type = render_latest()
    assert "text/plain" in content_type
    text = body.decode()
    for name in (
        "payguard_payment_requests_total",
        "payguard_payment_success_total",
        "payguard_payment_failure_total",
        "payguard_payment_processing_duration_seconds",
        "payguard_provider_latency_seconds",
        "payguard_provider_timeout_total",
        "payguard_idempotency_conflicts_total",
        "payguard_webhook_events_total",
        "payguard_webhook_duplicates_total",
        "payguard_refund_total",
        "payguard_refund_failures_total",
        "payguard_outbox_backlog",
        "payguard_reconciliation_mismatches_total",
    ):
        assert name in text, f"{name} missing from /metrics output"
