"""Proves the token bucket's atomicity under genuine concurrency -- the same
property tests/concurrency/test_idempotency_race.py proves for the database
claim, applied to Redis instead. Redis processes commands (including an
EVAL'd Lua script) one at a time regardless of how many clients call
concurrently, which is exactly what makes a Lua script the right tool here:
100 concurrent asyncio-gathered check_rate_limit() calls against the same
bucket still serialize at the Redis server, so a capacity of 20 must let
through exactly 20, never more (a naive read-tokens-then-write-tokens
implemented in Python, racing across 100 concurrent coroutines, would not
have this guarantee -- the same class of bug ADR-001 exists to prevent for
idempotency claims)."""

import asyncio
import collections
import uuid

from ratelimit import check_rate_limit

CONCURRENCY = 100
CAPACITY = 20


async def test_concurrent_requests_never_exceed_the_bucket_capacity(redis_client):
    merchant_id = uuid.uuid4()

    results = await asyncio.gather(
        *(
            # A tiny (not zero) refill rate avoids a division-by-zero in the
            # Lua script's TTL calculation while still being negligible over
            # this test's sub-second runtime -- effectively no refill.
            check_rate_limit(redis_client, merchant_id, capacity=CAPACITY, refill_per_second=0.0001)
            for _ in range(CONCURRENCY)
        )
    )

    counts = collections.Counter(results)
    assert counts[True] == CAPACITY, f"expected exactly {CAPACITY} allowed, got {counts}"
    assert counts[False] == CONCURRENCY - CAPACITY
