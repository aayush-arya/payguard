"""Integration tests proving observability is wired into real code paths,
not just present as standalone modules: a real payment creation increments
real Prometheus counters and emits a real span tree, and GET /metrics is
reachable end to end through the actual API."""

import uuid

from observability.metrics import payment_requests_total, payment_success_total
from observability.tracing import configure_tracing
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from payments.service import create_payment
from providers import MockProvider


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def test_metrics_endpoint_is_reachable_and_well_formed(api_client):
    response = await api_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "payguard_payment_requests_total" in response.text


async def test_creating_a_payment_through_the_real_api_increments_real_counters(
    api_client, merchant_with_key
):
    _, api_key = merchant_with_key
    before_requests = payment_requests_total._value.get()
    before_success = payment_success_total._value.get()

    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1500,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201

    assert payment_requests_total._value.get() == before_requests + 1
    assert payment_success_total._value.get() == before_success + 1


async def test_response_carries_a_request_id_usable_to_correlate_logs(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.get(f"/v1/payments/{uuid.uuid4()}", headers=_headers(api_key))
    assert response.headers["X-Request-Id"].startswith("req_")
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]


async def test_create_payment_emits_a_provider_authorize_span(db_session, merchant_id):
    """Exercises packages/payments/service.py directly (not through the live
    API app, which owns its own tracer configuration) to prove the span
    created around provider.authorize() is real, not just a module that
    imports cleanly."""
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)

    provider = MockProvider()
    await create_payment(
        db_session,
        merchant_id=merchant_id,
        idempotency_key=str(uuid.uuid4()),
        raw_body=b"{}",
        amount_minor=1000,
        currency="USD",
        merchant_reference=None,
        payment_token=f"pm_demo_{uuid.uuid4().hex}",
        provider=provider,
    )

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert "provider.authorize" in span_names


async def test_declined_payment_increments_the_declined_failure_reason_label(api_client, merchant_with_key):
    from observability.metrics import payment_failure_total

    _, api_key = merchant_with_key
    before = payment_failure_total.labels(reason="declined")._value.get()

    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": "pm_demo_declined"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert payment_failure_total.labels(reason="declined")._value.get() == before + 1


async def test_idempotency_conflict_increments_the_conflict_counter(api_client, merchant_with_key):
    from observability.metrics import idempotency_conflicts_total

    _, api_key = merchant_with_key
    key = str(uuid.uuid4())
    before = idempotency_conflicts_total._value.get()

    first = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, key),
    )
    assert first.status_code == 201

    second = await api_client.post(
        "/v1/payments",
        json={
            "amount": 5000,  # different amount -> fingerprint mismatch -> CONFLICT
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, key),
    )
    assert second.status_code == 409
    assert idempotency_conflicts_total._value.get() == before + 1
