"""Integration tests for the Phase 3 Payment API, exercised through a real
ASGI request/response cycle (httpx + ASGITransport) against a real Postgres
database -- not by calling packages.payments.service directly. This is what
actually proves auth, header parsing, and the error envelope work, not just
the business logic underneath them."""

import uuid

AUTH_TOKEN = "pm_demo_test"


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _payment_body(*, token: str = AUTH_TOKEN, amount: int = 4999, currency: str = "USD") -> dict:
    return {
        "amount": amount,
        "currency": currency,
        "merchant_reference": "order_123",
        "payment_method": {"type": "token", "token": token},
    }


async def test_create_payment_authorizes_and_leaves_it_processing(api_client, merchant_with_key):
    merchant_id, api_key = merchant_with_key
    key = f"key-{uuid.uuid4()}"

    response = await api_client.post("/v1/payments", json=_payment_body(), headers=_headers(api_key, key))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PROCESSING"
    assert body["amount"] == 4999
    assert body["currency"] == "USD"
    assert body["merchant_reference"] == "order_123"


async def test_create_payment_replays_identical_retry(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    key = f"key-{uuid.uuid4()}"
    body = _payment_body()

    first = await api_client.post("/v1/payments", json=body, headers=_headers(api_key, key))
    second = await api_client.post("/v1/payments", json=body, headers=_headers(api_key, key))

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


async def test_create_payment_rejects_reused_key_with_different_payload(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    key = f"key-{uuid.uuid4()}"

    first = await api_client.post(
        "/v1/payments", json=_payment_body(amount=1000), headers=_headers(api_key, key)
    )
    second = await api_client.post(
        "/v1/payments", json=_payment_body(amount=5000), headers=_headers(api_key, key)
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_create_payment_requires_idempotency_key(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.post("/v1/payments", json=_payment_body(), headers=_headers(api_key))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_create_payment_requires_authentication(api_client):
    response = await api_client.post(
        "/v1/payments", json=_payment_body(), headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_create_payment_rejects_invalid_api_key(api_client):
    response = await api_client.post(
        "/v1/payments",
        json=_payment_body(),
        headers={"Authorization": "Bearer sk_test_not_a_real_key", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 401


async def test_create_payment_rejects_non_positive_amount(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments", json=_payment_body(amount=0), headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


async def test_create_payment_rejects_malformed_currency(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json=_payment_body(currency="usd"),
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 400


async def test_declined_payment_lands_in_failed(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json=_payment_body(token="pm_demo_declined"),
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"


async def test_unknown_outcome_leaves_payment_unknown_not_failed(api_client, merchant_with_key):
    """The whole point of UNKNOWN: a lost response must never be silently
    treated as a failure (or a success) -- see ADR-005 and ADR-008."""
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json=_payment_body(token="pm_demo_timeout"),
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "UNKNOWN"


async def test_get_payment_returns_created_payment(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments", json=_payment_body(), headers=_headers(api_key, str(uuid.uuid4()))
    )
    payment_id = create.json()["id"]

    response = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key))
    assert response.status_code == 200
    assert response.json()["id"] == payment_id


async def test_get_payment_not_found(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.get(f"/v1/payments/{uuid.uuid4()}", headers=_headers(api_key))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PAYMENT_NOT_FOUND"


async def test_merchant_cannot_read_another_merchants_payment(api_client, merchant_with_key, db_session):
    """Tenant isolation (docs/architecture.md section 18): Merchant A must
    never be able to access Merchant B's payment, even by guessing/reusing a
    valid payment id."""
    from database.models import Merchant

    _, api_key_a = merchant_with_key
    api_key_b = "sk_test_merchant_b_" + uuid.uuid4().hex
    from domain.security import hash_api_key

    merchant_b = Merchant(name="Merchant B", api_key_hash=hash_api_key(api_key_b))
    db_session.add(merchant_b)
    await db_session.commit()

    create = await api_client.post(
        "/v1/payments", json=_payment_body(), headers=_headers(api_key_a, str(uuid.uuid4()))
    )
    payment_id = create.json()["id"]

    response = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key_b))
    assert response.status_code == 404


async def test_merchant_cannot_capture_another_merchants_payment(api_client, merchant_with_key, db_session):
    """Same tenant-isolation guarantee (docs/architecture.md section 18),
    for a mutating endpoint this time -- Merchant B must not be able to
    capture funds on Merchant A's payment just by knowing its id."""
    from database.models import Merchant
    from domain.security import hash_api_key

    _, api_key_a = merchant_with_key
    api_key_b = "sk_test_merchant_b_" + uuid.uuid4().hex
    merchant_b = Merchant(name="Merchant B", api_key_hash=hash_api_key(api_key_b))
    db_session.add(merchant_b)
    await db_session.commit()

    create = await api_client.post(
        "/v1/payments", json=_payment_body(), headers=_headers(api_key_a, str(uuid.uuid4()))
    )
    payment_id = create.json()["id"]
    assert create.json()["status"] == "PROCESSING"

    capture = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key_b, str(uuid.uuid4()))
    )
    assert capture.status_code == 404

    # And genuinely untouched -- not just a 404 while secretly capturing.
    still_processing = await api_client.get(f"/v1/payments/{payment_id}", headers=_headers(api_key_a))
    assert still_processing.json()["status"] == "PROCESSING"


async def test_capture_moves_processing_payment_to_succeeded(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments", json=_payment_body(), headers=_headers(api_key, str(uuid.uuid4()))
    )
    payment_id = create.json()["id"]
    assert create.json()["status"] == "PROCESSING"

    capture = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert capture.status_code == 200
    assert capture.json()["status"] == "SUCCEEDED"


async def test_capture_is_idempotent_no_op_when_already_succeeded(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments", json=_payment_body(), headers=_headers(api_key, str(uuid.uuid4()))
    )
    payment_id = create.json()["id"]

    first = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    second = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "SUCCEEDED"


async def test_capture_of_declined_payment_is_rejected(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments",
        json=_payment_body(token="pm_demo_declined"),
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment_id = create.json()["id"]
    assert create.json()["status"] == "FAILED"

    capture = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert capture.status_code == 422
    assert capture.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_health_and_ready_endpoints(api_client):
    health = await api_client.get("/v1/health")
    assert health.status_code == 200

    ready = await api_client.get("/v1/ready")
    assert ready.status_code == 200


async def test_response_includes_request_id_header(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.get(f"/v1/payments/{uuid.uuid4()}", headers=_headers(api_key))
    assert "X-Request-Id" in response.headers
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]
