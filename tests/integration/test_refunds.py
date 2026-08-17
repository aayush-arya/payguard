"""Integration tests for refunds (Phase 8) against a real Postgres database:
full/partial refunds, the balance invariant, refund idempotency, the refund
state machine (including retry-after-failure), and tenant isolation."""

import uuid


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _create_succeeded_payment(api_client, api_key: str, amount: int = 10000) -> str:
    create = await api_client.post(
        "/v1/payments",
        json={
            "amount": amount,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert create.status_code == 201
    payment_id = create.json()["id"]

    capture = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert capture.status_code == 200
    assert capture.json()["status"] == "SUCCEEDED"
    return payment_id


async def _refund(api_client, api_key: str, payment_id: str, amount: int, idempotency_key: str | None = None):
    return await api_client.post(
        f"/v1/payments/{payment_id}/refunds",
        json={"amount": amount},
        headers=_headers(api_key, idempotency_key or str(uuid.uuid4())),
    )


async def test_full_refund_moves_payment_to_refunded(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=10000)

    response = await _refund(api_client, api_key, payment_id, 10000)
    assert response.status_code == 201
    assert response.json()["status"] == "SUCCEEDED"
    assert response.json()["amount"] == 10000

    payment = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert payment.json()["status"] == "REFUNDED"


async def test_partial_refunds_summing_exactly_to_full_amount_succeed(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=10000)

    first = await _refund(api_client, api_key, payment_id, 3000)
    assert first.status_code == 201
    payment_after_first = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert payment_after_first.json()["status"] == "SUCCEEDED", "not yet fully refunded"

    second = await _refund(api_client, api_key, payment_id, 2000)
    assert second.status_code == 201
    payment_after_second = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert payment_after_second.json()["status"] == "SUCCEEDED"

    third = await _refund(api_client, api_key, payment_id, 5000)
    assert third.status_code == 201
    payment_after_third = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert payment_after_third.json()["status"] == "REFUNDED", "fully refunded after the third partial refund"


async def test_refund_exceeding_remaining_balance_is_rejected(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=10000)

    full = await _refund(api_client, api_key, payment_id, 10000)
    assert full.status_code == 201

    extra = await _refund(api_client, api_key, payment_id, 2000)
    assert extra.status_code == 422  # payment is REFUNDED (terminal), not just over-budget
    assert extra.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_partial_refund_exceeding_remaining_balance_is_rejected(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=10000)

    first = await _refund(api_client, api_key, payment_id, 7000)
    assert first.status_code == 201

    second = await _refund(api_client, api_key, payment_id, 5000)  # 7000 + 5000 > 10000
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "REFUND_EXCEEDS_PAYMENT"


async def test_refund_of_unsettled_payment_is_rejected(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments",
        json={
            "amount": 5000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment_id = create.json()["id"]
    assert create.json()["status"] == "PROCESSING"  # authorized but never captured

    response = await _refund(api_client, api_key, payment_id, 1000)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_refund_replays_on_retry_with_same_idempotency_key(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=5000)
    key = str(uuid.uuid4())

    first = await _refund(api_client, api_key, payment_id, 2000, idempotency_key=key)
    second = await _refund(api_client, api_key, payment_id, 2000, idempotency_key=key)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


async def test_refund_rejects_reused_key_with_different_amount(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=5000)
    key = str(uuid.uuid4())

    first = await _refund(api_client, api_key, payment_id, 1000, idempotency_key=key)
    second = await _refund(api_client, api_key, payment_id, 2000, idempotency_key=key)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_declined_refund_moves_payment_to_refund_failed(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=5000)

    response = await _refund(
        api_client, api_key, payment_id, 1000, idempotency_key=f"refund-declined-{uuid.uuid4()}"
    )
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"

    payment = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert payment.json()["status"] == "REFUND_FAILED"


async def test_refund_can_be_retried_after_a_failed_attempt(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=5000)

    failed = await _refund(
        api_client, api_key, payment_id, 1000, idempotency_key=f"refund-declined-{uuid.uuid4()}"
    )
    assert failed.json()["status"] == "FAILED"

    retried = await _refund(api_client, api_key, payment_id, 1000)
    assert retried.status_code == 201
    assert retried.json()["status"] == "SUCCEEDED"

    payment = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert payment.json()["status"] == "SUCCEEDED"  # partial refund, not yet fully refunded


async def test_get_refund_returns_refund(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, amount=5000)
    created = await _refund(api_client, api_key, payment_id, 2000)
    refund_id = created.json()["id"]

    response = await api_client.get(f"/v1/refunds/{refund_id}", headers=_headers(api_key))
    assert response.status_code == 200
    assert response.json()["id"] == refund_id
    assert response.json()["amount"] == 2000


async def test_get_refund_not_found(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.get(f"/v1/refunds/{uuid.uuid4()}", headers=_headers(api_key))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REFUND_NOT_FOUND"


async def test_merchant_cannot_read_another_merchants_refund(api_client, merchant_with_key, db_session):
    from database.models import Merchant
    from domain.security import generate_api_key, hash_api_key

    api_key_a = merchant_with_key[1]
    api_key_b = generate_api_key()
    merchant_b = Merchant(name="Merchant B", api_key_hash=hash_api_key(api_key_b))
    db_session.add(merchant_b)
    await db_session.commit()

    payment_id = await _create_succeeded_payment(api_client, api_key_a, amount=5000)
    created = await _refund(api_client, api_key_a, payment_id, 1000)
    refund_id = created.json()["id"]

    response = await api_client.get(f"/v1/refunds/{refund_id}", headers=_headers(api_key_b))
    assert response.status_code == 404
