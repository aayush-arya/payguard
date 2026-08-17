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
