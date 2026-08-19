from __future__ import annotations

from uuid import UUID

from database.models import Merchant
from domain.errors import PayGuardError
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from payments.service import (
    capture_payment,
    create_payment,
    get_payment,
    get_payment_detail,
    list_payments,
    refund_payment,
    serialize_payment,
)
from providers.base import PaymentProvider
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import enforce_rate_limit, get_current_merchant, get_db_session, get_provider
from apps.api.schemas import PaymentCreateRequest, RefundCreateRequest

router = APIRouter(prefix="/v1/payments", tags=["payments"])


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise PayGuardError("IDEMPOTENCY_KEY_REQUIRED", "The Idempotency-Key header is required.")
    return idempotency_key


@router.post("", status_code=201, response_model=None, dependencies=[Depends(enforce_rate_limit)])
async def create_payment_endpoint(
    payload: PaymentCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
    provider: PaymentProvider = Depends(get_provider),
) -> dict:
    key = _require_idempotency_key(idempotency_key)
    raw_body = await request.body()
    customer_ip = payload.customer_ip or (request.client.host if request.client else None)

    status_code, body = await create_payment(
        db_session,
        merchant_id=merchant.id,
        idempotency_key=key,
        raw_body=raw_body,
        amount_minor=payload.amount,
        currency=payload.currency,
        merchant_reference=payload.merchant_reference,
        payment_token=payload.payment_method.token,
        provider=provider,
        billing_country=payload.billing_country,
        shipping_country=payload.shipping_country,
        customer_ip=customer_ip,
    )
    response.status_code = status_code
    return body


@router.get("", response_model=None)
async def list_payments_endpoint(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    items, total = await list_payments(
        db_session, merchant_id=merchant.id, status=status, limit=limit, offset=offset
    )
    return {
        "items": [serialize_payment(intent) for intent in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{payment_id}", response_model=None)
async def get_payment_endpoint(
    payment_id: UUID,
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    intent = await get_payment(db_session, merchant_id=merchant.id, payment_id=payment_id)
    return serialize_payment(intent)


@router.get("/{payment_id}/detail", response_model=None)
async def get_payment_detail_endpoint(
    payment_id: UUID,
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict:
    return await get_payment_detail(db_session, merchant_id=merchant.id, payment_id=payment_id)


@router.post("/{payment_id}/capture", response_model=None, dependencies=[Depends(enforce_rate_limit)])
async def capture_payment_endpoint(
    payment_id: UUID,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
    provider: PaymentProvider = Depends(get_provider),
) -> dict:
    key = _require_idempotency_key(idempotency_key)
    raw_body = await request.body()

    status_code, body = await capture_payment(
        db_session,
        merchant_id=merchant.id,
        payment_id=payment_id,
        idempotency_key=key,
        raw_body=raw_body,
        provider=provider,
    )
    response.status_code = status_code
    return body


@router.post(
    "/{payment_id}/refunds", status_code=201, response_model=None, dependencies=[Depends(enforce_rate_limit)]
)
async def create_refund_endpoint(
    payment_id: UUID,
    payload: RefundCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_session),
    provider: PaymentProvider = Depends(get_provider),
) -> dict:
    key = _require_idempotency_key(idempotency_key)
    raw_body = await request.body()

    status_code, body = await refund_payment(
        db_session,
        merchant_id=merchant.id,
        payment_id=payment_id,
        idempotency_key=key,
        raw_body=raw_body,
        amount_minor=payload.amount,
        provider=provider,
    )
    response.status_code = status_code
    return body
