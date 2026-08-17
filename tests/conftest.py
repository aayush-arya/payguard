from __future__ import annotations

import os
import pathlib
import uuid

import pytest_asyncio
from database.models import Merchant
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
