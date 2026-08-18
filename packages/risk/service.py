"""Rule-based risk/fraud engine (product brief section 20).

Deterministic and explainable by design -- every signal is a plain
threshold check against data already in this database, no ML, no external
scoring service, no claim to being a production fraud model. The point is
to demonstrate where a real risk engine would plug into the payment flow
(packages/payments/service.py assesses risk right before calling the
provider, see docs/risk.md) and how its decision propagates: BLOCK stops
the payment before the provider is ever called, everything else is
observational (recorded, not acted on).

Each signal's weight is a plain integer chosen so the total score lands in
an intuitive band -- there is no calibration against real fraud data behind
these numbers, they exist to make the LOW/MEDIUM/HIGH/BLOCK banding legible
in tests and demos.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from database.models import PaymentAttempt, PaymentIntent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

VELOCITY_WINDOW = timedelta(minutes=5)
VELOCITY_THRESHOLD = 5  # payment_intents created by this merchant in the window
REPEATED_FAILURE_THRESHOLD = 3  # DECLINED attempts by this merchant in the window

LARGE_AMOUNT_THRESHOLD_MINOR = 500_000  # $5,000
VERY_LARGE_AMOUNT_THRESHOLD_MINOR = 2_000_000  # $20,000

# Reserved-for-documentation IP ranges (RFC 5737) -- no real customer traffic
# ever legitimately originates here, which makes them safe, deterministic
# stand-ins for "a known-bad IP" in tests and demos without needing a real
# IP reputation service.
HIGH_RISK_IP_PREFIXES = ("198.51.100.", "203.0.113.")

BLOCK_THRESHOLD = 100
HIGH_THRESHOLD = 60
MEDIUM_THRESHOLD = 30


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RiskSignal:
    name: str
    weight: int
    description: str


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    score: int
    signals: tuple[RiskSignal, ...]

    def as_dict(self) -> dict:
        return {
            "level": self.level.value,
            "score": self.score,
            "signals": [
                {"name": s.name, "weight": s.weight, "description": s.description} for s in self.signals
            ],
        }


def _level_for_score(score: int) -> RiskLevel:
    if score >= BLOCK_THRESHOLD:
        return RiskLevel.BLOCK
    if score >= HIGH_THRESHOLD:
        return RiskLevel.HIGH
    if score >= MEDIUM_THRESHOLD:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _amount_signal(amount_minor: int) -> RiskSignal | None:
    if amount_minor >= VERY_LARGE_AMOUNT_THRESHOLD_MINOR:
        return RiskSignal(
            "VERY_LARGE_AMOUNT", 50, f"amount_minor {amount_minor} >= {VERY_LARGE_AMOUNT_THRESHOLD_MINOR}"
        )
    if amount_minor >= LARGE_AMOUNT_THRESHOLD_MINOR:
        return RiskSignal(
            "LARGE_AMOUNT", 20, f"amount_minor {amount_minor} >= {LARGE_AMOUNT_THRESHOLD_MINOR}"
        )
    return None


def _country_mismatch_signal(billing_country: str | None, shipping_country: str | None) -> RiskSignal | None:
    if billing_country and shipping_country and billing_country != shipping_country:
        return RiskSignal(
            "BILLING_SHIPPING_COUNTRY_MISMATCH",
            25,
            f"billing_country={billing_country} != shipping_country={shipping_country}",
        )
    return None


def _high_risk_ip_signal(customer_ip: str | None) -> RiskSignal | None:
    if customer_ip and any(customer_ip.startswith(prefix) for prefix in HIGH_RISK_IP_PREFIXES):
        return RiskSignal("HIGH_RISK_IP", 35, f"customer_ip {customer_ip} matches a known high-risk range")
    return None


async def _velocity_signal(session: AsyncSession, merchant_id: uuid.UUID, now: datetime) -> RiskSignal | None:
    count = (
        await session.execute(
            select(func.count())
            .select_from(PaymentIntent)
            .where(
                PaymentIntent.merchant_id == merchant_id, PaymentIntent.created_at >= now - VELOCITY_WINDOW
            )
        )
    ).scalar_one()
    if count >= VELOCITY_THRESHOLD:
        return RiskSignal(
            "HIGH_VELOCITY",
            30,
            f"{count} payments created by this merchant in the last {VELOCITY_WINDOW}",
        )
    return None


async def _repeated_failures_signal(
    session: AsyncSession, merchant_id: uuid.UUID, now: datetime
) -> RiskSignal | None:
    count = (
        await session.execute(
            select(func.count())
            .select_from(PaymentAttempt)
            .join(PaymentIntent, PaymentAttempt.payment_intent_id == PaymentIntent.id)
            .where(
                PaymentIntent.merchant_id == merchant_id,
                PaymentAttempt.status == "DECLINED",
                PaymentAttempt.created_at >= now - VELOCITY_WINDOW,
            )
        )
    ).scalar_one()
    if count >= REPEATED_FAILURE_THRESHOLD:
        return RiskSignal(
            "REPEATED_FAILURES",
            40,
            f"{count} declined attempts by this merchant in the last {VELOCITY_WINDOW} "
            "(possible card testing)",
        )
    return None


async def assess_payment_risk(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    amount_minor: int,
    billing_country: str | None = None,
    shipping_country: str | None = None,
    customer_ip: str | None = None,
) -> RiskAssessment:
    now = datetime.now(UTC)
    signals = [
        s
        for s in (
            _amount_signal(amount_minor),
            _country_mismatch_signal(billing_country, shipping_country),
            _high_risk_ip_signal(customer_ip),
            await _velocity_signal(session, merchant_id, now),
            await _repeated_failures_signal(session, merchant_id, now),
        )
        if s is not None
    ]
    score = sum(s.weight for s in signals)
    return RiskAssessment(level=_level_for_score(score), score=score, signals=tuple(signals))
