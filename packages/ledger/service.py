"""Double-entry ledger writer (ADR-007).

Every financial event writes exactly two immutable rows -- a debit and a
credit of equal amount, sharing a ledger_transaction_id -- inside the same
database transaction as the state transition that caused it (the caller is
responsible for that; these functions only `session.add()`, they never
commit). This is what lets `sum(debits) == sum(credits)` become a checkable
invariant instead of a hope: a bug that drops or duplicates a write is
detectable by summing, not something you have to trust the code got right.

Ledger writes are tied to *specific financial events* (a payment settling, a
refund settling), not to generic state-machine transitions -- see
docs/ledger.md for why the obvious-looking "write ledger entries whenever a
payment reaches SUCCEEDED" would double-count a payment that returns to
SUCCEEDED after a partial refund.

Entry-pair *construction* (`_build_pair`) is kept separate from the
`session.add()` side effect so the balance invariant -- every pair this
module can produce has equal debit and credit amounts -- is directly
property-testable without a database (tests/property/test_ledger_invariants.py).
"""

from __future__ import annotations

import uuid

from database.models import LedgerEntry
from sqlalchemy.ext.asyncio import AsyncSession

MERCHANT_RECEIVABLE = "Merchant Receivable"
PAYMENT_CLEARING = "Payment Clearing"
REFUND_LIABILITY = "Refund Liability"


def _entry(
    *,
    payment_intent_id: uuid.UUID,
    ledger_transaction_id: uuid.UUID,
    account: str,
    direction: str,
    amount_minor: int,
) -> LedgerEntry:
    return LedgerEntry(
        payment_intent_id=payment_intent_id,
        ledger_transaction_id=ledger_transaction_id,
        account=account,
        direction=direction,
        amount_minor=amount_minor,
    )


def build_payment_settled_pair(
    *, payment_intent_id: uuid.UUID, amount_minor: int
) -> tuple[LedgerEntry, LedgerEntry]:
    """A payment newly settled (authorized funds were actually captured).
    Debit what the merchant is now owed; credit the clearing account holding
    the settled funds until they're paid out."""
    ledger_transaction_id = uuid.uuid4()
    debit = _entry(
        payment_intent_id=payment_intent_id,
        ledger_transaction_id=ledger_transaction_id,
        account=MERCHANT_RECEIVABLE,
        direction="DEBIT",
        amount_minor=amount_minor,
    )
    credit = _entry(
        payment_intent_id=payment_intent_id,
        ledger_transaction_id=ledger_transaction_id,
        account=PAYMENT_CLEARING,
        direction="CREDIT",
        amount_minor=amount_minor,
    )
    return debit, credit


def build_refund_settled_pair(
    *, payment_intent_id: uuid.UUID, amount_minor: int
) -> tuple[LedgerEntry, LedgerEntry]:
    """A refund newly settled. Debit the refund liability (money now owed
    back out); credit merchant receivable (reducing what they're owed by the
    refunded amount)."""
    ledger_transaction_id = uuid.uuid4()
    debit = _entry(
        payment_intent_id=payment_intent_id,
        ledger_transaction_id=ledger_transaction_id,
        account=REFUND_LIABILITY,
        direction="DEBIT",
        amount_minor=amount_minor,
    )
    credit = _entry(
        payment_intent_id=payment_intent_id,
        ledger_transaction_id=ledger_transaction_id,
        account=MERCHANT_RECEIVABLE,
        direction="CREDIT",
        amount_minor=amount_minor,
    )
    return debit, credit


async def record_payment_settled(
    session: AsyncSession, *, payment_intent_id: uuid.UUID, amount_minor: int
) -> uuid.UUID:
    debit, credit = build_payment_settled_pair(payment_intent_id=payment_intent_id, amount_minor=amount_minor)
    session.add(debit)
    session.add(credit)
    return debit.ledger_transaction_id


async def record_refund_settled(
    session: AsyncSession, *, payment_intent_id: uuid.UUID, amount_minor: int
) -> uuid.UUID:
    debit, credit = build_refund_settled_pair(payment_intent_id=payment_intent_id, amount_minor=amount_minor)
    session.add(debit)
    session.add(credit)
    return debit.ledger_transaction_id
