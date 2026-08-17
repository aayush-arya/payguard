"""Idempotency key claim/replay protocol (ADR-001).

The safety guarantee here comes from a single mechanism: the database unique
constraint on (merchant_id, idempotency_key), raced against via
`INSERT ... ON CONFLICT DO NOTHING`. Everything else in this module -- reading
back the loser's row, comparing fingerprints, deciding whether a stale PENDING
row is safe to reclaim -- is just deciding what to tell the caller. None of it
is what makes duplicate creation impossible; the constraint is.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from database.models import IdempotencyKey
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_STALE_AFTER = timedelta(seconds=30)


def compute_fingerprint(method: str, path: str, body: bytes) -> str:
    """Fingerprint over method + path + raw body, so the same key reused with
    a different payload is detected even if headers or query strings vary."""
    hasher = hashlib.sha256()
    hasher.update(method.upper().encode())
    hasher.update(b"\n")
    hasher.update(path.encode())
    hasher.update(b"\n")
    hasher.update(body)
    return hasher.hexdigest()


class ClaimOutcome(StrEnum):
    CLAIMED = "CLAIMED"  # this call won the race (or reclaimed an abandoned attempt); proceed
    REPLAY = "REPLAY"  # a prior call already completed; replay its stored response verbatim
    CONFLICT = "CONFLICT"  # same key, different request fingerprint -- reject, do not merge
    IN_PROGRESS = "IN_PROGRESS"  # another call is actively processing this key right now


@dataclass(frozen=True)
class ClaimResult:
    outcome: ClaimOutcome
    key_row: IdempotencyKey


async def claim_idempotency_key(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    idempotency_key: str,
    request_fingerprint: str,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> ClaimResult:
    now = datetime.now(UTC)

    insert_stmt = (
        pg_insert(IdempotencyKey)
        .values(
            merchant_id=merchant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            status="PENDING",
            locked_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_keys_merchant_key")
        .returning(IdempotencyKey)
    )
    won = (await session.execute(insert_stmt)).scalar_one_or_none()
    if won is not None:
        return ClaimResult(outcome=ClaimOutcome.CLAIMED, key_row=won)

    existing = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.merchant_id == merchant_id,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one()

    if existing.request_fingerprint != request_fingerprint:
        return ClaimResult(outcome=ClaimOutcome.CONFLICT, key_row=existing)

    if existing.status == "COMPLETED":
        return ClaimResult(outcome=ClaimOutcome.REPLAY, key_row=existing)

    if existing.status == "FAILED":
        # The prior attempt errored before producing a response -- same
        # fingerprint means this is a legitimate retry of the same logical
        # request, safe to let through as a fresh attempt.
        reclaimed = await _reclaim(session, existing, expected_status="FAILED", now=now)
        if reclaimed is not None:
            return ClaimResult(outcome=ClaimOutcome.CLAIMED, key_row=reclaimed)
        return await claim_idempotency_key(
            session,
            merchant_id=merchant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            stale_after=stale_after,
        )

    # status == "PENDING": either genuinely in flight, or the process handling
    # it crashed and never got to COMPLETED/FAILED. locked_at age is the only
    # signal we have to tell those apart.
    locked_at = existing.locked_at or existing.created_at
    if now - locked_at < stale_after:
        return ClaimResult(outcome=ClaimOutcome.IN_PROGRESS, key_row=existing)

    reclaimed = await _reclaim(
        session, existing, expected_status="PENDING", now=now, expected_locked_at=locked_at
    )
    if reclaimed is not None:
        return ClaimResult(outcome=ClaimOutcome.CLAIMED, key_row=reclaimed)
    # Someone else reclaimed it first, or it made progress -- re-evaluate from scratch.
    return await claim_idempotency_key(
        session,
        merchant_id=merchant_id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        stale_after=stale_after,
    )


async def _reclaim(
    session: AsyncSession,
    row: IdempotencyKey,
    *,
    expected_status: str,
    now: datetime,
    expected_locked_at: datetime | None = None,
) -> IdempotencyKey | None:
    """Atomically flip an abandoned row back to PENDING under a fresh lock
    window. The WHERE clause re-checks the same condition the caller already
    observed; under READ COMMITTED, Postgres re-evaluates it after acquiring
    the row lock, so a concurrent reclaimer that loses the race affects zero
    rows instead of double-reclaiming."""
    stmt = (
        update(IdempotencyKey)
        .where(IdempotencyKey.id == row.id, IdempotencyKey.status == expected_status)
        .values(
            status="PENDING",
            locked_at=now,
            payment_intent_id=None,
            response_status=None,
            response_body=None,
        )
        .returning(IdempotencyKey)
    )
    if expected_locked_at is not None:
        stmt = stmt.where(
            (IdempotencyKey.locked_at == expected_locked_at)
            if row.locked_at is not None
            else IdempotencyKey.locked_at.is_(None)
        )
    return (await session.execute(stmt)).scalar_one_or_none()


async def complete_idempotency_key(
    session: AsyncSession,
    key_row: IdempotencyKey,
    *,
    payment_intent_id: uuid.UUID | None,
    response_status: int,
    response_body: dict,
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == key_row.id)
        .values(
            status="COMPLETED",
            payment_intent_id=payment_intent_id,
            response_status=response_status,
            response_body=response_body,
        )
    )


async def fail_idempotency_key(session: AsyncSession, key_row: IdempotencyKey) -> None:
    await session.execute(
        update(IdempotencyKey).where(IdempotencyKey.id == key_row.id).values(status="FAILED")
    )
