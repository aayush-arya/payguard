from __future__ import annotations

import os
import pathlib
import uuid

import pytest_asyncio
from database.models import Merchant
from domain.security import generate_api_key, hash_api_key
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _load_dotenv() -> None:
    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

# Every concurrent "request" in a concurrency test needs its own real
# connection to actually exercise Postgres row-level locking -- NullPool
# means each AsyncSession checks out a fresh connection instead of sharing a
# small pool that would serialize what should be concurrent traffic.
TABLES_TO_TRUNCATE = (
    "audit_logs",
    "ledger_entries",
    "webhook_events",
    "outbox_events",
    "payment_events",
    "refunds",
    "idempotency_keys",
    "provider_transactions",
    "payment_attempts",
    "payment_intents",
    "payment_methods",
    "customers",
    "merchants",
)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE " + ", ".join(TABLES_TO_TRUNCATE) + " CASCADE"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
def db_sessionmaker(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(db_sessionmaker) -> AsyncSession:
    async with db_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def merchant_id(db_session: AsyncSession) -> uuid.UUID:
    merchant = Merchant(name="Test Merchant", api_key_hash="hash_" + uuid.uuid4().hex)
    db_session.add(merchant)
    await db_session.commit()
    return merchant.id


@pytest_asyncio.fixture
async def merchant_with_key(db_session: AsyncSession) -> tuple[uuid.UUID, str]:
    api_key = generate_api_key()
    merchant = Merchant(name="Test Merchant", api_key_hash=hash_api_key(api_key))
    db_session.add(merchant)
    await db_session.commit()
    return merchant.id, api_key


@pytest_asyncio.fixture
async def api_client(db_engine):
    """An httpx client wired directly to the FastAPI ASGI app -- no real
    socket, but a real request/response cycle through routing, dependency
    injection, and the actual Postgres database `db_engine` just truncated.

    database.session.get_engine()/get_sessionmaker() are process-wide
    lru_cache singletons -- correct for a real long-lived app with one event
    loop, but pytest-asyncio gives each test function its own event loop, and
    asyncpg connections can't be reused across event loops. Reset the cache
    (and dispose the previous engine) so the app under test always gets an
    engine bound to the current test's loop.
    """
    import database.session as session_module

    from apps.api.main import app

    old_engine = session_module.get_engine.cache_info()
    if old_engine.currsize:
        await session_module.get_engine().dispose()
    session_module.get_engine.cache_clear()
    session_module.get_sessionmaker.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    await session_module.get_engine().dispose()
    session_module.get_engine.cache_clear()
    session_module.get_sessionmaker.cache_clear()
