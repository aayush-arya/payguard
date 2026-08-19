"""Integration tests for merchant-scoped rate limiting (Phase 16,
docs/security.md) at the real HTTP boundary."""

import uuid

RATE_LIMIT_ENV = {"RATE_LIMIT_CAPACITY": "3", "RATE_LIMIT_REFILL_PER_SECOND": "0.01"}


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _set_low_limits(monkeypatch) -> None:
    # ratelimit.service reads these from the environment fresh on every
    # call (not once at import), specifically so a test can lower the
    # limit like this without needing to reach into the module's internals.
    for key, value in RATE_LIMIT_ENV.items():
        monkeypatch.setenv(key, value)


async def test_requests_within_the_limit_succeed(api_client, merchant_with_key, redis_client, monkeypatch):
    _set_low_limits(monkeypatch)
    _, api_key = merchant_with_key

    for _ in range(3):
        response = await api_client.post(
            "/v1/payments",
            json={
                "amount": 1000,
                "currency": "USD",
                "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
            },
            headers=_headers(api_key, str(uuid.uuid4())),
        )
        assert response.status_code == 201


async def test_requests_beyond_the_limit_are_rejected_with_429(
    api_client, merchant_with_key, redis_client, monkeypatch
):
    _set_low_limits(monkeypatch)
    _, api_key = merchant_with_key

    for _ in range(3):
        await api_client.post(
            "/v1/payments",
            json={
                "amount": 1000,
                "currency": "USD",
                "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
            },
            headers=_headers(api_key, str(uuid.uuid4())),
        )

    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


async def test_rate_limit_is_scoped_per_merchant(
    api_client, db_session, merchant_with_key, redis_client, monkeypatch
):
    from database.models import Merchant
    from domain.security import generate_api_key, hash_api_key

    _set_low_limits(monkeypatch)
    _, api_key_a = merchant_with_key
    api_key_b = generate_api_key()
    db_session.add(Merchant(name="Merchant B", api_key_hash=hash_api_key(api_key_b)))
    await db_session.commit()

    for _ in range(3):
        await api_client.post(
            "/v1/payments",
            json={
                "amount": 1000,
                "currency": "USD",
                "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
            },
            headers=_headers(api_key_a, str(uuid.uuid4())),
        )
    exhausted = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key_a, str(uuid.uuid4())),
    )
    assert exhausted.status_code == 429

    still_fresh = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key_b, str(uuid.uuid4())),
    )
    assert still_fresh.status_code == 201


async def test_read_endpoints_are_not_rate_limited(api_client, merchant_with_key, redis_client, monkeypatch):
    _set_low_limits(monkeypatch)
    _, api_key = merchant_with_key

    responses = [await api_client.get("/v1/payments", headers=_headers(api_key)) for _ in range(10)]
    assert all(r.status_code == 200 for r in responses)
