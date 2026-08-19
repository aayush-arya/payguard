"""Unit tests for rotate_api_key() (Phase 16, docs/security.md) -- pure
in-memory object mutation, no database needed to prove the logic itself."""

from datetime import UTC, datetime, timedelta

from database.models import Merchant
from domain.security import hash_api_key
from merchants import rotate_api_key


def _merchant(api_key: str) -> Merchant:
    return Merchant(name="Test Merchant", api_key_hash=hash_api_key(api_key))


async def test_rotation_issues_a_new_key_that_is_not_the_old_one():
    old_key = "sk_test_original"
    merchant = _merchant(old_key)
    new_key = await rotate_api_key(merchant)
    assert new_key != old_key
    assert merchant.api_key_hash == hash_api_key(new_key)


async def test_rotation_preserves_the_old_key_as_previous_with_an_expiry():
    old_key = "sk_test_original"
    merchant = _merchant(old_key)
    await rotate_api_key(merchant)

    assert merchant.previous_api_key_hash == hash_api_key(old_key)
    assert merchant.previous_api_key_expires_at is not None
    assert merchant.previous_api_key_expires_at > datetime.now(UTC)


async def test_rotation_overlap_window_is_configurable():
    merchant = _merchant("sk_test_original")
    before = datetime.now(UTC)
    await rotate_api_key(merchant, overlap=timedelta(hours=1))
    after = datetime.now(UTC)

    assert (
        before + timedelta(minutes=59)
        < merchant.previous_api_key_expires_at
        < after + timedelta(hours=1, minutes=1)
    )


async def test_a_second_rotation_discards_the_first_previous_key():
    """Two rotations in quick succession mean only the *second* previous key
    (i.e. the key active immediately before the most recent rotation) stays
    valid -- the very first key is fully retired, not resurrected."""
    merchant = _merchant("sk_test_original")
    first_new_key = await rotate_api_key(merchant)
    await rotate_api_key(merchant)

    assert merchant.previous_api_key_hash == hash_api_key(first_new_key)
    assert merchant.api_key_hash != hash_api_key(first_new_key)
