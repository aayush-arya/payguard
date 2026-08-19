from __future__ import annotations

import os
from functools import lru_cache

from redis.asyncio import Redis


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL is not set")
    return url


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(_redis_url(), decode_responses=True)
