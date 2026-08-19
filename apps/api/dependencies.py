from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from database.models import Merchant
from database.session import get_sessionmaker
from domain.errors import PayGuardError
from domain.security import hash_api_key
from fastapi import Depends, Header, Request
from observability import merchant_id_var, rate_limit_rejections_total
from providers.base import PaymentProvider
from ratelimit import check_rate_limit, get_redis
from redis.asyncio import Redis
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


async def get_current_merchant(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    authorization: str | None = Header(default=None),
) -> Merchant:
    if authorization is None or not authorization.startswith("Bearer "):
        raise PayGuardError("UNAUTHORIZED", "Missing or malformed Authorization header.")
    api_key = authorization.removeprefix("Bearer ").strip()
    if not api_key:
        raise PayGuardError("UNAUTHORIZED", "Missing or malformed Authorization header.")

    key_hash = hash_api_key(api_key)
    # Accepts the current key, or -- during the overlap window
    # rotate_api_key() (packages/merchants/service.py) creates -- the
    # immediately-previous one, so an already-deployed integration keeps
    # working while it's updated to a newly rotated key.
    merchant = (
        await db_session.execute(
            select(Merchant).where(
                or_(
                    Merchant.api_key_hash == key_hash,
                    and_(
                        Merchant.previous_api_key_hash == key_hash,
                        Merchant.previous_api_key_expires_at > datetime.now(UTC),
                    ),
                )
            )
        )
    ).scalar_one_or_none()
    if merchant is None or merchant.status != "active":
        raise PayGuardError("UNAUTHORIZED", "Invalid API key.")

    request.state.merchant_id = merchant.id
    # Set (not bind-and-reset): this request's ASGI task keeps its own
    # contextvars copy, so there's nothing to leak into sibling requests --
    # and there's no clean point to "unset" it before the request finishes
    # anyway, since every downstream log line for this request wants it.
    merchant_id_var.set(str(merchant.id))
    return merchant


def get_provider(request: Request) -> PaymentProvider:
    return request.app.state.provider


async def enforce_rate_limit(
    merchant: Merchant = Depends(get_current_merchant),
    redis: Redis = Depends(get_redis),
) -> None:
    """Applied to the payment-mutation endpoints (create/capture/refund) --
    not every GET, which are cheap reads a legitimate integration might poll
    frequently. FastAPI caches `Depends(get_current_merchant)` per request,
    so an endpoint that already depends on it directly doesn't pay for a
    second auth lookup here."""
    if not await check_rate_limit(redis, merchant.id):
        rate_limit_rejections_total.inc()
        raise PayGuardError("RATE_LIMITED", "Too many requests. Please try again shortly.")
