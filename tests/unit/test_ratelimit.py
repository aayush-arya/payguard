"""Unit tests for the Redis-backed token bucket (Phase 16, docs/security.md)
against a real Redis instance -- the algorithm's correctness depends on the
Lua script's atomicity, which a mock can't meaningfully stand in for."""

import time
import uuid

from ratelimit import check_rate_limit


async def test_requests_within_capacity_are_allowed(redis_client):
    merchant_id = uuid.uuid4()
    for _ in range(5):
        assert await check_rate_limit(redis_client, merchant_id, capacity=5, refill_per_second=1)


async def test_requests_beyond_capacity_are_rejected(redis_client):
    merchant_id = uuid.uuid4()
    for _ in range(5):
        await check_rate_limit(redis_client, merchant_id, capacity=5, refill_per_second=1)
    assert not await check_rate_limit(redis_client, merchant_id, capacity=5, refill_per_second=1)


async def test_bucket_refills_over_time(redis_client):
    merchant_id = uuid.uuid4()
    for _ in range(3):
        await check_rate_limit(redis_client, merchant_id, capacity=3, refill_per_second=10)
    assert not await check_rate_limit(redis_client, merchant_id, capacity=3, refill_per_second=10)

    time.sleep(0.2)  # 10 tokens/sec * 0.2s = ~2 tokens back
    assert await check_rate_limit(redis_client, merchant_id, capacity=3, refill_per_second=10)


async def test_refill_never_exceeds_capacity(redis_client):
    merchant_id = uuid.uuid4()
    await check_rate_limit(redis_client, merchant_id, capacity=3, refill_per_second=100)
    time.sleep(0.2)  # would refill far past capacity if not clamped

    outcomes = [
        await check_rate_limit(redis_client, merchant_id, capacity=3, refill_per_second=100)
        for _ in range(10)
    ]
    allowed_count = sum(outcomes)
    # 2 tokens remained after the first check, refilled (clamped) to at most
    # 3 -- never enough to satisfy all 10 follow-up requests.
    assert allowed_count < 10


async def test_different_merchants_have_independent_buckets(redis_client):
    merchant_a = uuid.uuid4()
    merchant_b = uuid.uuid4()
    for _ in range(5):
        await check_rate_limit(redis_client, merchant_a, capacity=5, refill_per_second=1)

    assert not await check_rate_limit(redis_client, merchant_a, capacity=5, refill_per_second=1)
    assert await check_rate_limit(redis_client, merchant_b, capacity=5, refill_per_second=1)
