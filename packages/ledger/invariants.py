"""Ledger balance invariant checks (ADR-007). Read-only -- nothing here
writes to the ledger, only verifies it.

The per-transaction check is cheap and synchronous with any single write
(the ledger writer itself is constructed to always balance by pairing every
debit with a credit, so this is really a check on the *schema/writer*
invariant, useful in tests). The global check is the one that matters
operationally: it's a multi-row read across the whole table, which is why
ADR-002/ADR-007 call out SERIALIZABLE isolation for it specifically -- a
concurrently-committing ledger write could otherwise produce a torn read
that looks unbalanced when nothing is actually wrong.
"""

from __future__ import annotations

import uuid

from database.models import LedgerEntry
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _sum_by_direction(
    session: AsyncSession, direction: str, ledger_transaction_id: uuid.UUID | None = None
) -> int:
    stmt = select(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)).where(
        LedgerEntry.direction == direction
    )
    if ledger_transaction_id is not None:
        stmt = stmt.where(LedgerEntry.ledger_transaction_id == ledger_transaction_id)
    return (await session.execute(stmt)).scalar_one()


async def ledger_transaction_is_balanced(session: AsyncSession, ledger_transaction_id: uuid.UUID) -> bool:
    debits = await _sum_by_direction(session, "DEBIT", ledger_transaction_id)
    credits = await _sum_by_direction(session, "CREDIT", ledger_transaction_id)
    return debits == credits


async def global_ledger_balance(session: AsyncSession) -> tuple[int, int]:
    """Returns (total_debits, total_credits) across the entire ledger."""
    debits = await _sum_by_direction(session, "DEBIT")
    credits = await _sum_by_direction(session, "CREDIT")
    return debits, credits


async def find_unbalanced_ledger_transactions(session: AsyncSession) -> list[uuid.UUID]:
    """GROUP BY ledger_transaction_id HAVING sum(debit) != sum(credit).
    Should always return an empty list -- this is the reconciliation-style
    audit query an operator (or a future scheduled job) runs to catch a
    writer bug that somehow produced an unbalanced transaction despite the
    writer always constructing paired entries."""
    stmt = (
        select(LedgerEntry.ledger_transaction_id)
        .group_by(LedgerEntry.ledger_transaction_id)
        .having(
            func.sum(case((LedgerEntry.direction == "DEBIT", LedgerEntry.amount_minor), else_=0))
            != func.sum(case((LedgerEntry.direction == "CREDIT", LedgerEntry.amount_minor), else_=0))
        )
    )
    return list((await session.execute(stmt)).scalars().all())
