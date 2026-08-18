from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PaymentMethodIn(BaseModel):
    type: Literal["token"]
    token: str = Field(min_length=1)


class PaymentCreateRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in minor units (e.g. cents).")
    currency: str = Field(min_length=3, max_length=3)
    merchant_reference: str | None = None
    payment_method: PaymentMethodIn
    # All optional -- feed the risk engine (packages/risk) when a merchant's
    # checkout flow has them, but nothing requires them. Omitting all three
    # just means those signals never fire.
    billing_country: str | None = Field(default=None, description="ISO 3166-1 alpha-2, e.g. 'US'.")
    shipping_country: str | None = Field(default=None, description="ISO 3166-1 alpha-2, e.g. 'US'.")
    customer_ip: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency_must_be_iso4217_shaped(cls, value: str) -> str:
        if not value.isalpha() or value != value.upper():
            raise ValueError("currency must be a 3-letter uppercase ISO 4217 code")
        return value


class PaymentResponse(BaseModel):
    id: UUID
    status: str
    amount: int
    currency: str
    merchant_reference: str | None
    created_at: datetime
    updated_at: datetime


class RefundCreateRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in minor units (e.g. cents).")


class RefundResponse(BaseModel):
    id: UUID
    payment_id: UUID
    amount: int
    status: str
    created_at: datetime


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    limit: int
    offset: int


class PaymentEventResponse(BaseModel):
    id: UUID
    from_status: str | None
    to_status: str
    actor: str
    created_at: datetime


class PaymentAttemptResponse(BaseModel):
    id: UUID
    provider_name: str
    status: str
    failure_classification: str | None
    attempt_number: int
    created_at: datetime


class LedgerEntryResponse(BaseModel):
    id: UUID
    ledger_transaction_id: UUID
    account: str
    direction: str
    amount: int
    created_at: datetime


class PaymentDetailResponse(PaymentResponse):
    events: list[PaymentEventResponse]
    attempts: list[PaymentAttemptResponse]
    refunds: list[RefundResponse]
    ledger_entries: list[LedgerEntryResponse]


class DashboardSummaryResponse(BaseModel):
    counts_by_status: dict[str, int]
    total_payments: int
    total_succeeded_amount: int
    total_refunded_amount: int


class ReconciliationReportResponse(BaseModel):
    id: UUID
    payment_id: UUID
    result: str
    internal_status: str
    provider_status: str | None
    details: dict
    created_at: datetime


class ReconciliationRunResponse(BaseModel):
    reports: list[ReconciliationReportResponse]
