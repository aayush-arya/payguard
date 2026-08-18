"""Integration tests for risk assessment (Phase 11) against a real Postgres
database: velocity and repeated-failure signals (which need real payment
history to evaluate), and the end-to-end BLOCK path through the payment API."""

import uuid

from database.models import AuditLog, PaymentAttempt, PaymentIntent
from risk import RiskLevel, assess_payment_risk
from sqlalchemy import select


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def test_no_history_and_small_amount_is_low_risk(db_session, merchant_id):
    assessment = await assess_payment_risk(db_session, merchant_id=merchant_id, amount_minor=1000)
    assert assessment.level is RiskLevel.LOW
    assert assessment.score == 0
    assert assessment.signals == ()


async def test_velocity_signal_fires_after_enough_recent_payments(db_session, merchant_id):
    from risk.service import VELOCITY_THRESHOLD

    for _ in range(VELOCITY_THRESHOLD):
        db_session.add(
            PaymentIntent(merchant_id=merchant_id, amount_minor=100, currency="USD", status="CREATED")
        )
    await db_session.commit()

    assessment = await assess_payment_risk(db_session, merchant_id=merchant_id, amount_minor=1000)
    assert any(s.name == "HIGH_VELOCITY" for s in assessment.signals)


async def test_repeated_failures_signal_fires_after_enough_recent_declines(db_session, merchant_id):
    from risk.service import REPEATED_FAILURE_THRESHOLD

    intent = PaymentIntent(merchant_id=merchant_id, amount_minor=100, currency="USD", status="FAILED")
    db_session.add(intent)
    await db_session.flush()
    for i in range(REPEATED_FAILURE_THRESHOLD):
        db_session.add(
            PaymentAttempt(
                payment_intent_id=intent.id,
                provider_name="mock",
                status="DECLINED",
                failure_classification="PERMANENT",
                attempt_number=i + 1,
            )
        )
    await db_session.commit()

    assessment = await assess_payment_risk(db_session, merchant_id=merchant_id, amount_minor=1000)
    assert any(s.name == "REPEATED_FAILURES" for s in assessment.signals)


async def test_every_assessment_is_recorded_to_audit_log(api_client, merchant_with_key, db_sessionmaker):
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    payment_id = response.json()["id"]

    async with db_sessionmaker() as session:
        logs = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.actor == "RISK_ENGINE", AuditLog.action == "payment.risk_assessed"
                    )
                )
            )
            .scalars()
            .all()
        )
    matching = [log for log in logs if log.audit_metadata.get("payment_id") == payment_id]
    assert len(matching) == 1
    assert matching[0].audit_metadata["level"] == "LOW"


async def test_high_risk_ip_and_large_amount_together_block_the_payment(api_client, merchant_with_key):
    """Two signals (HIGH_RISK_IP=35, VERY_LARGE_AMOUNT=50) sum past
    BLOCK_THRESHOLD=100 only when combined with a third -- use amounts and an
    IP chosen so the combination crosses the line, proving multiple weak
    signals compound into a hard block rather than needing one dominant one."""
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 2_500_000,  # VERY_LARGE_AMOUNT (50)
            "currency": "USD",
            "billing_country": "US",
            "shipping_country": "RU",  # BILLING_SHIPPING_COUNTRY_MISMATCH (25)
            "customer_ip": "203.0.113.7",  # HIGH_RISK_IP (35) -- total 110 >= BLOCK_THRESHOLD
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"


async def test_blocked_payment_never_creates_a_payment_attempt(
    api_client, merchant_with_key, db_sessionmaker
):
    """A blocked payment must never reach the provider -- no attempt row,
    because we genuinely never asked (docs/risk.md)."""
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 2_500_000,
            "currency": "USD",
            "billing_country": "US",
            "shipping_country": "RU",
            "customer_ip": "203.0.113.7",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment_id = response.json()["id"]
    assert response.json()["status"] == "FAILED"

    async with db_sessionmaker() as session:
        attempts = (
            (
                await session.execute(
                    select(PaymentAttempt).where(PaymentAttempt.payment_intent_id == uuid.UUID(payment_id))
                )
            )
            .scalars()
            .all()
        )
    assert attempts == []


async def test_low_risk_payment_proceeds_normally(api_client, merchant_with_key):
    _, api_key = merchant_with_key
    response = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "PROCESSING"
