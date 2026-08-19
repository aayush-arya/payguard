"""Merchant-scoped rate limiting (Phase 16, docs/security.md, ADR discussion
referenced by docs/architecture.md section 13). Token buckets held in Redis,
not in-process memory, so the limit is shared correctly across horizontally
scaled API replicas -- a per-process counter would let a merchant get N
times the intended limit just by spreading requests across N replicas.

The check-and-decrement has to be a single atomic operation, for exactly the
reason ADR-001 requires idempotency claims to be a single INSERT rather than
a SELECT-then-INSERT: two concurrent requests each reading "3 tokens left"
and independently deciding to proceed would let both through even though
only one token's worth of capacity actually remained. A Lua script executed
via EVAL is Redis's mechanism for that atomicity -- the whole script runs
as one indivisible operation, no different in spirit from this codebase's
reliance on a single database transaction elsewhere.
"""

from __future__ import annotations

import os
import time
import uuid

from redis.asyncio import Redis


def _default_capacity() -> int:
    return int(os.environ.get("RATE_LIMIT_CAPACITY", "20"))


def _default_refill_per_second() -> float:
    return float(os.environ.get("RATE_LIMIT_REFILL_PER_SECOND", "5"))


# KEYS[1] = bucket key
# ARGV[1] = capacity (max tokens the bucket can hold)
# ARGV[2] = refill_per_second (tokens regenerated per second)
# ARGV[3] = now (unix timestamp, float seconds)
#
# Lazily refills based on elapsed wall-clock time since the last check,
# rather than a background job ticking every bucket -- a merchant with no
# traffic costs nothing to "maintain," and a bucket that hasn't been
# touched in a while is simply full (capped at `capacity`) the next time
# it's read, which is mathematically identical to having refilled the
# whole time.
_TOKEN_BUCKET_SCRIPT = """
local tokens_key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', tokens_key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_per_second)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HSET', tokens_key, 'tokens', tostring(tokens), 'last_refill', tostring(now))
-- A bucket idle long enough to fully refill has nothing left to remember;
-- let Redis reclaim it instead of retaining rate-limit state forever for
-- a merchant that stopped sending traffic.
local ttl_seconds = math.ceil(capacity / refill_per_second) + 60
redis.call('EXPIRE', tokens_key, ttl_seconds)

return allowed
"""


async def check_rate_limit(
    redis: Redis,
    merchant_id: uuid.UUID,
    *,
    capacity: int | None = None,
    refill_per_second: float | None = None,
) -> bool:
    """Returns True if the request may proceed (and consumes one token),
    False if the merchant's bucket is currently empty.

    `capacity`/`refill_per_second` read the environment at call time, not
    once at import -- a plain `= DEFAULT_CAPACITY` parameter default would
    bind whatever RATE_LIMIT_CAPACITY was set to when this module first
    loaded, permanently, which is both wrong for tests that need to adjust
    the limit per-test and wrong in spirit: every other env-configured
    value in this codebase (packages/database/session.py's pool sizes) is
    read fresh, not frozen at import time.
    """
    capacity = capacity if capacity is not None else _default_capacity()
    refill_per_second = refill_per_second if refill_per_second is not None else _default_refill_per_second()
    key = f"ratelimit:{merchant_id}"
    allowed = await redis.eval(_TOKEN_BUCKET_SCRIPT, 1, key, capacity, refill_per_second, time.time())
    return bool(allowed)
