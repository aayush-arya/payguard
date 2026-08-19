"""Integration tests for API key rotation (Phase 16, docs/security.md) at
the real HTTP auth boundary (apps/api/dependencies.get_current_merchant)."""

from datetime import UTC, datetime, timedelta

from database.models import Merchant
from merchants import rotate_api_key


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


async def test_new_key_authenticates_after_rotation(api_client, db_session, merchant_with_key):
    merchant_id, _old_key = merchant_with_key
    merchant = await db_session.get(Merchant, merchant_id)
    new_key = await rotate_api_key(merchant)
    await db_session.commit()

    response = await api_client.get("/v1/dashboard/summary", headers=_headers(new_key))
    assert response.status_code == 200


async def test_old_key_still_works_during_the_overlap_window(api_client, db_session, merchant_with_key):
    merchant_id, old_key = merchant_with_key
    merchant = await db_session.get(Merchant, merchant_id)
    await rotate_api_key(merchant)
    await db_session.commit()

    response = await api_client.get("/v1/dashboard/summary", headers=_headers(old_key))
    assert response.status_code == 200


async def test_old_key_is_rejected_once_the_overlap_window_expires(api_client, db_session, merchant_with_key):
    merchant_id, old_key = merchant_with_key
    merchant = await db_session.get(Merchant, merchant_id)
    await rotate_api_key(merchant, overlap=timedelta(seconds=-1))  # expires immediately
    await db_session.commit()

    response = await api_client.get("/v1/dashboard/summary", headers=_headers(old_key))
    assert response.status_code == 401


async def test_a_key_retired_by_a_second_rotation_is_rejected(api_client, db_session, merchant_with_key):
    """Only the immediately-previous key stays valid -- rotating twice fully
    retires the key from before the first rotation, not just the current one."""
    merchant_id, original_key = merchant_with_key
    merchant = await db_session.get(Merchant, merchant_id)
    await rotate_api_key(merchant)
    await db_session.commit()

    merchant = await db_session.get(Merchant, merchant_id)
    await rotate_api_key(merchant)
    await db_session.commit()

    response = await api_client.get("/v1/dashboard/summary", headers=_headers(original_key))
    assert response.status_code == 401


async def test_rotation_does_not_affect_other_merchants(api_client, db_session, merchant_with_key):
    from domain.security import generate_api_key, hash_api_key

    merchant_id, _old_key = merchant_with_key
    other_key = generate_api_key()
    other_merchant = Merchant(name="Other Merchant", api_key_hash=hash_api_key(other_key))
    db_session.add(other_merchant)
    await db_session.commit()

    merchant = await db_session.get(Merchant, merchant_id)
    await rotate_api_key(merchant)
    await db_session.commit()

    response = await api_client.get("/v1/dashboard/summary", headers=_headers(other_key))
    assert response.status_code == 200


async def test_previous_key_expiry_is_persisted(db_session, merchant_with_key):
    merchant_id, _old_key = merchant_with_key
    merchant = await db_session.get(Merchant, merchant_id)
    await rotate_api_key(merchant, overlap=timedelta(hours=1))
    await db_session.commit()

    reloaded = await db_session.get(Merchant, merchant_id)
    assert reloaded.previous_api_key_expires_at is not None
    assert reloaded.previous_api_key_expires_at > datetime.now(UTC)
