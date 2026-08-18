"""Endpoints that exist only for the dashboard (Phase 13) -- aggregate
reads and the on-demand reconciliation trigger ADR-008 describes but never
had a caller for until now."""

from __future__ import annotations

from database.models import Merchant
from fastapi import APIRouter, Depends
from payments.service import get_dashboard_summary
from providers.base import PaymentProvider
from reconciliation import run_reconciliation_pass, serialize_reconciliation_report
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_merchant, get_db_session, get_provider

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=None)
async def get_dashboard_summary_endpoint(
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    return await get_dashboard_summary(db_session, merchant_id=merchant.id)


@router.post("/reconciliation/run", response_model=None)
async def run_reconciliation_endpoint(
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
    provider: PaymentProvider = Depends(get_provider),
) -> dict:
    reports = await run_reconciliation_pass(db_session, provider, merchant_id=merchant.id)
    return {"reports": [serialize_reconciliation_report(r) for r in reports]}
