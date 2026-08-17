"""Provider abstraction (ADR-004). Every provider adapter -- MockProvider now,
real adapters later -- implements this protocol and translates its own
native responses into the closed ProviderOutcome vocabulary. Nothing outside
this package (state machine, payments service, retry classification) ever
branches on a provider-specific status string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ProviderOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AuthorizeRequest:
    amount_minor: int
    currency: str
    token: str
    idempotency_key: str


@dataclass(frozen=True)
class ProviderResult:
    outcome: ProviderOutcome
    provider_transaction_id: str | None
    raw_status: str
    raw_response: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    name: str

    async def authorize(self, request: AuthorizeRequest) -> ProviderResult: ...

    async def capture(self, provider_transaction_id: str, amount_minor: int) -> ProviderResult: ...

    async def refund(
        self, provider_transaction_id: str, amount_minor: int, idempotency_key: str
    ) -> ProviderResult: ...

    async def get_payment_status(self, provider_transaction_id: str) -> ProviderResult: ...
