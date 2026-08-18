"""Integration tests for the dashboard-facing endpoints (Phase 13):
GET /v1/payments (list), GET /v1/payments/{id}/detail, GET /v1/dashboard/summary,
and POST /v1/dashboard/reconciliation/run."""

import uuid

from database.models import Merchant
from domain.security import generate_api_key, hash_api_key


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _create_payment(api_client, api_key: str, token: str = "pm_demo_ok", amount: int = 1000) -> dict:
    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": amount,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"{token}_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    return response.json()


async def test_list_payments_is_scoped_to_the_authenticated_merchant(api_client, db_session):
    key_a = generate_api_key()
    merchant_a = Merchant(name="Merchant A", api_key_hash=hash_api_key(key_a))
    key_b = generate_api_key()
    merchant_b = Merchant(name="Merchant B", api_key_hash=hash_api_key(key_b))
    db_session.add_all([merchant_a, merchant_b])
    await db_session.commit()

    await _create_payment(api_client, key_a)
    await _create_payment(api_client, key_a)
    await _create_payment(api_client, key_b)

    response = await api_client.get("/v1/payments", headers=_headers(key_a))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


async def test_list_payments_supports_status_filter_and_pagination(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    for _ in range(3):
        await _create_payment(api_client, api_key)
    for _ in range(2):
        await _create_payment(api_client, api_key, token="pm_demo_declined")

    declined = await api_client.get("/v1/payments", params={"status": "FAILED"}, headers=_headers(api_key))
    assert declined.status_code == 200
    assert declined.json()["total"] == 2
    assert all(item["status"] == "FAILED" for item in declined.json()["items"])

    page = await api_client.get("/v1/payments", params={"limit": 2, "offset": 0}, headers=_headers(api_key))
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


async def test_list_payments_orders_newest_first(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    first = await _create_payment(api_client, api_key)
    second = await _create_payment(api_client, api_key)

    response = await api_client.get("/v1/payments", headers=_headers(api_key))
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [second["id"], first["id"]]


async def test_payment_detail_includes_events_and_attempts(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment = await _create_payment(api_client, api_key)

    response = await api_client.get(f"/v1/payments/{payment['id']}/detail", headers=_headers(api_key))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == payment["id"]
    assert len(body["events"]) >= 2  # CREATED, then PROCESSING (at least)
    assert len(body["attempts"]) == 1
    assert body["attempts"][0]["status"] == "SUCCEEDED"
    assert body["refunds"] == []
    assert body["ledger_entries"] == []


async def test_payment_detail_includes_ledger_entries_after_capture(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment = await _create_payment(api_client, api_key)

    capture = await api_client.post(
        f"/v1/payments/{payment['id']}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert capture.status_code == 200

    response = await api_client.get(f"/v1/payments/{payment['id']}/detail", headers=_headers(api_key))
    body = response.json()
    assert len(body["ledger_entries"]) == 2
    accounts = {entry["account"] for entry in body["ledger_entries"]}
    assert accounts == {"Merchant Receivable", "Payment Clearing"}


async def test_payment_detail_for_unknown_id_returns_404(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.get(f"/v1/payments/{uuid.uuid4()}/detail", headers=_headers(api_key))
    assert response.status_code == 404


async def test_payment_detail_is_scoped_to_the_authenticated_merchant(api_client, db_session):
    key_a = generate_api_key()
    merchant_a = Merchant(name="Merchant A", api_key_hash=hash_api_key(key_a))
    key_b = generate_api_key()
    merchant_b = Merchant(name="Merchant B", api_key_hash=hash_api_key(key_b))
    db_session.add_all([merchant_a, merchant_b])
    await db_session.commit()

    payment = await _create_payment(api_client, key_a)

    response = await api_client.get(f"/v1/payments/{payment['id']}/detail", headers=_headers(key_b))
    assert response.status_code == 404


async def test_dashboard_summary_reflects_real_counts_and_volume(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    ok_one = await _create_payment(api_client, api_key, amount=1000)
    await _create_payment(api_client, api_key, amount=2000)
    await _create_payment(api_client, api_key, token="pm_demo_declined")

    await api_client.post(
        f"/v1/payments/{ok_one['id']}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )

    response = await api_client.get("/v1/dashboard/summary", headers=_headers(api_key))
    assert response.status_code == 200
    body = response.json()
    assert body["total_payments"] == 3
    assert body["counts_by_status"]["FAILED"] == 1
    assert body["total_succeeded_amount"] == 1000


async def test_reconciliation_run_endpoint_only_touches_the_calling_merchants_payments(
    api_client, db_session
):
    key_a = generate_api_key()
    merchant_a = Merchant(name="Merchant A", api_key_hash=hash_api_key(key_a))
    key_b = generate_api_key()
    merchant_b = Merchant(name="Merchant B", api_key_hash=hash_api_key(key_b))
    db_session.add_all([merchant_a, merchant_b])
    await db_session.commit()

    mine = await api_client.post(
        "/v1/payments",
        json={
            "amount": 5000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_timeout_{uuid.uuid4().hex}"},
        },
        headers=_headers(key_a, str(uuid.uuid4())),
    )
    theirs = await api_client.post(
        "/v1/payments",
        json={
            "amount": 5000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_timeout_{uuid.uuid4().hex}"},
        },
        headers=_headers(key_b, str(uuid.uuid4())),
    )
    assert mine.json()["status"] == "UNKNOWN"
    assert theirs.json()["status"] == "UNKNOWN"

    response = await api_client.post("/v1/dashboard/reconciliation/run", headers=_headers(key_a))
    assert response.status_code == 200
    reports = response.json()["reports"]
    payment_ids = {r["payment_id"] for r in reports}
    assert mine.json()["id"] in payment_ids
    assert theirs.json()["id"] not in payment_ids
