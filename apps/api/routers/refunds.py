from __future__ import annotations

from uuid import UUID

from database.models import Merchant
from fastapi import APIRouter, Depends
from payments.service import get_refund, serialize_refund
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_merchant, get_db_session

router = APIRouter(prefix="/v1/refunds", tags=["refunds"])


@router.get("/{refund_id}", response_model=None)
async def get_refund_endpoint(
    refund_id: UUID,
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    refund = await get_refund(db_session, merchant_id=merchant.id, refund_id=refund_id)
    return serialize_refund(refund)
