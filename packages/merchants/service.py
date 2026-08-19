"""Merchant lifecycle operations (Phase 16, docs/security.md).

There is no HTTP endpoint for any of this, same reasoning as
scripts/seed_merchant.py: merchant provisioning and credential lifecycle
are out-of-band, operator-driven actions on real payment platforms, not
self-service API calls a merchant's own (possibly-compromised) key could
trigger against itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from database.models import Merchant
from domain.security import generate_api_key, hash_api_key

DEFAULT_OVERLAP = timedelta(hours=24)


async def rotate_api_key(merchant: Merchant, *, overlap: timedelta = DEFAULT_OVERLAP) -> str:
    """Issues a new API key, moving the current one to `previous_api_key_hash`
    with an expiry rather than deleting it outright -- an already-deployed
    integration keeps working with its old key for the overlap window while
    it's updated, instead of breaking the instant this call returns. Only
    one prior key is ever retained: a second rotation during the overlap
    window discards whatever was in `previous_api_key_hash` before it, on
    the assumption that an operator rotating twice in quick succession means
    the first rotation's overlap grace is no longer wanted either.

    Caller is responsible for adding `merchant` to a session and committing;
    this function only mutates the in-memory object, matching every other
    service function in this codebase (docs/architecture.md section 8).
    """
    new_api_key = generate_api_key()
    merchant.previous_api_key_hash = merchant.api_key_hash
    merchant.previous_api_key_expires_at = datetime.now(UTC) + overlap
    merchant.api_key_hash = hash_api_key(new_api_key)
    return new_api_key
