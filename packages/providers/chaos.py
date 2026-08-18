"""Chaos injection (Phase 14, product brief section 25): a PaymentProvider
wrapper that probabilistically corrupts what a merchant-facing authorize()
call sees, exercising the system's UNKNOWN/reconciliation machinery under
random rather than hand-picked failure, without needing a hostile network
to actually be running.

Scope: only authorize() outcomes are corrupted (forced to UNKNOWN). Two
narrower additions were deliberately left out:

- capture()/refund() outcome corruption. MockProvider.refund() has no
  UNKNOWN branch at all (refund_payment() in packages/payments/service.py
  treats anything that isn't SUCCEEDED as FAILED) -- corrupting refund
  responses would be exercising a code path that was never designed to
  receive UNKNOWN, not a real resilience story. capture() *happens* to
  work correctly under corruption (MockProvider.capture() always truly
  succeeds; a corrupted UNKNOWN response just means reconciliation later
  re-discovers that true SUCCEEDED via the same idempotency-key lookup a
  corrupted authorize() would use), but relying on that coincidence for a
  documented chaos surface felt like the wrong thing to advertise.
- raising raw exceptions from authorize(). create_payment() has no
  handling path for a provider call raising outright -- it would fail the
  idempotency claim and force the caller to retry with a fresh key, which
  is a real and valid failure mode, but a different one from what this
  phase is demonstrating (the outcome-classification and reconciliation
  machinery already built in Phases 3/6/10).

Corruption happens *after* delegating to the wrapped provider, never
instead of it -- the wrapped provider's own true-outcome bookkeeping
(MockProvider._true_outcomes) is always populated correctly, so
reconciliation's get_payment_status_by_idempotency_key() call still finds
the truth. This mirrors MockProvider's own `pm_demo_timeout` scenario,
generalized from "triggered by a token" to "triggered by a weighted coin
flip with a reproducible seed."
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from providers.base import AuthorizeRequest, PaymentProvider, ProviderOutcome, ProviderResult


@dataclass(frozen=True)
class ChaosConfig:
    unknown_rate: float = 0.0
    """Probability an authorize() call's caller-visible outcome is forced
    to UNKNOWN, regardless of what actually happened."""
    slow_rate: float = 0.0
    """Probability a call (authorize/capture/refund) is delayed before
    returning, simulating provider latency."""
    slow_delay_seconds: float = 0.5
    seed: int | None = None


class ChaosProvider:
    name = "chaos"

    def __init__(self, inner: PaymentProvider, config: ChaosConfig | None = None) -> None:
        self._inner = inner
        self._config = config or ChaosConfig()
        self._rng = random.Random(self._config.seed)

    async def _maybe_delay(self) -> None:
        if self._config.slow_rate and self._rng.random() < self._config.slow_rate:
            await asyncio.sleep(self._config.slow_delay_seconds)

    async def authorize(self, request: AuthorizeRequest) -> ProviderResult:
        result = await self._inner.authorize(request)
        await self._maybe_delay()
        if self._config.unknown_rate and self._rng.random() < self._config.unknown_rate:
            return ProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                provider_transaction_id=None,
                raw_status="chaos_injected_unknown",
                raw_response={},
            )
        return result

    async def capture(self, provider_transaction_id: str, amount_minor: int) -> ProviderResult:
        result = await self._inner.capture(provider_transaction_id, amount_minor)
        await self._maybe_delay()
        return result

    async def refund(
        self, provider_transaction_id: str, amount_minor: int, idempotency_key: str
    ) -> ProviderResult:
        result = await self._inner.refund(provider_transaction_id, amount_minor, idempotency_key)
        await self._maybe_delay()
        return result

    async def get_payment_status(self, provider_transaction_id: str) -> ProviderResult:
        # Never corrupted -- this and get_payment_status_by_idempotency_key
        # are reconciliation's only way to learn the truth, exactly like a
        # real PSP's status-lookup API. Corrupting these would make
        # reconciliation itself unreliable rather than testing the system's
        # response to an unreliable *authorize* call.
        return await self._inner.get_payment_status(provider_transaction_id)

    async def get_payment_status_by_idempotency_key(self, idempotency_key: str) -> ProviderResult:
        return await self._inner.get_payment_status_by_idempotency_key(idempotency_key)
