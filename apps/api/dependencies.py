from __future__ import annotations

from collections.abc import AsyncIterator

from database.models import Merchant
from database.session import get_sessionmaker
from domain.errors import PayGuardError
from domain.security import hash_api_key
from fastapi import Depends, Header, Request
from providers.base import PaymentProvider
from sqlalchemy import select
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

    merchant = (
        await db_session.execute(select(Merchant).where(Merchant.api_key_hash == hash_api_key(api_key)))
    ).scalar_one_or_none()
    if merchant is None or merchant.status != "active":
        raise PayGuardError("UNAUTHORIZED", "Invalid API key.")

    request.state.merchant_id = merchant.id
    return merchant


def get_provider(request: Request) -> PaymentProvider:
    return request.app.state.provider
