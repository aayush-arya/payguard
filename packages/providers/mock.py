"""Deterministic mock payment provider (ADR-004). Lets the rest of the system
exercise every failure mode from docs/architecture.md section 9 without any
network flakiness standing in for a deliberately-chosen test scenario.

Scenario selection is driven by substrings in the payment method token
(`pm_demo_declined`, `pm_demo_timeout`, ...) so a test or demo picks its
scenario just by choosing which token to send -- no separate control channel
needed. DUPLICATE_RESPONSE isn't a token marker: it's exercised by calling
`authorize()` twice with the same idempotency_key, which is exactly what a
real provider's own idempotency layer would do on a retried request, and
exactly what this project's concurrency tests already do.

The `timeout` and `unknown_result` scenarios track two separate outcomes: the
*caller-visible* response (always UNKNOWN -- "we never got a clean answer")
and the *true* outcome the provider actually recorded internally. This is
what makes reconciliation (Phase 10) meaningful to test: `authorize()` genuinely
can't tell you what happened, but `get_payment_status_by_idempotency_key()` can,
exactly like asking a real PSP "what happened to idempotency key X?" days
later once you're not blocked waiting on the original request.
"""

from __future__ import annotations

import asyncio
import uuid

from providers.base import AuthorizeRequest, ProviderOutcome, ProviderResult

_DECLINED = "declined"
_TIMEOUT = "timeout"
_TEMPORARY_FAILURE = "temp_fail"
_UNKNOWN_RESULT = "unknown_result"
_STILL_UNKNOWN = "still_unknown"
_SLOW = "slow"

_SCENARIO_MARKERS = (_DECLINED, _TIMEOUT, _TEMPORARY_FAILURE, _UNKNOWN_RESULT, _STILL_UNKNOWN, _SLOW)


class MockProvider:
    name = "mock"

    def __init__(self, *, slow_response_delay: float = 1.0) -> None:
        self._slow_response_delay = slow_response_delay
        # Keyed by idempotency_key, mirroring a real provider's own
        # idempotency layer -- a second authorize() call with the same key
        # replays the first call's result instead of authorizing twice.
        self._authorizations: dict[str, ProviderResult] = {}
        # What actually happened, which may differ from what authorize()
        # returned (only for the timeout/unknown_result scenarios -- every
        # other scenario's true outcome equals its caller-visible one).
        self._true_outcomes: dict[str, ProviderResult] = {}

    def _scenario_for(self, token: str) -> str | None:
        for marker in _SCENARIO_MARKERS:
            if marker in token:
                return marker
        return None

    async def authorize(self, request: AuthorizeRequest) -> ProviderResult:
        cached = self._authorizations.get(request.idempotency_key)
        if cached is not None:
            return cached

        scenario = self._scenario_for(request.token)
        if scenario == _SLOW:
            await asyncio.sleep(self._slow_response_delay)
            scenario = None

        if scenario == _DECLINED:
            result = ProviderResult(
                outcome=ProviderOutcome.DECLINED,
                provider_transaction_id=None,
                raw_status="card_declined",
                raw_response={"reason": "insufficient_funds"},
            )
            true_result = result
        elif scenario == _TEMPORARY_FAILURE:
            result = ProviderResult(
                outcome=ProviderOutcome.TEMPORARY_FAILURE,
                provider_transaction_id=None,
                raw_status="provider_unavailable",
                raw_response={},
            )
            true_result = result
        elif scenario == _TIMEOUT:
            # The provider actually processes this successfully -- the
            # response is what got lost, not the payment. Only revealed via
            # get_payment_status_by_idempotency_key(), never by retrying
            # authorize() with the same key (that just replays UNKNOWN
            # again, matching ADR-005's "never blindly retry" rule).
            provider_transaction_id = f"ptx_{uuid.uuid4().hex[:16]}"
            true_result = ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_transaction_id=provider_transaction_id,
                raw_status="authorized",
                raw_response={"amount_minor": request.amount_minor, "currency": request.currency},
            )
            result = ProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                provider_transaction_id=None,
                raw_status="no_response_received",
                raw_response={},
            )
        elif scenario == _UNKNOWN_RESULT:
            # Same idea, but the provider's own truth is a decline --
            # reconciliation must resolve to FAILED just as readily as
            # SUCCEEDED, not assume "unknown" always means "actually fine".
            true_result = ProviderResult(
                outcome=ProviderOutcome.DECLINED,
                provider_transaction_id=None,
                raw_status="card_declined",
                raw_response={"reason": "insufficient_funds"},
            )
            result = ProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                provider_transaction_id=None,
                raw_status="ambiguous_response",
                raw_response={},
            )
        elif scenario == _STILL_UNKNOWN:
            # The rarer, harder case: even the provider itself can't answer
            # yet. Reconciliation must be able to report STILL_UNKNOWN
            # rather than force a resolution.
            result = ProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                provider_transaction_id=None,
                raw_status="processing",
                raw_response={},
            )
            true_result = result
        else:
            provider_transaction_id = f"ptx_{uuid.uuid4().hex[:16]}"
            result = ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_transaction_id=provider_transaction_id,
                raw_status="authorized",
                raw_response={"amount_minor": request.amount_minor, "currency": request.currency},
            )
            true_result = result

        self._authorizations[request.idempotency_key] = result
        self._true_outcomes[request.idempotency_key] = true_result
        return result

    async def capture(self, provider_transaction_id: str, amount_minor: int) -> ProviderResult:
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_transaction_id=provider_transaction_id,
            raw_status="captured",
            raw_response={"amount_minor": amount_minor},
        )

    async def refund(
        self, provider_transaction_id: str, amount_minor: int, idempotency_key: str
    ) -> ProviderResult:
        # refund() has no token to carry a scenario marker, so it's read
        # from the idempotency_key instead -- e.g. a test choosing
        # f"refund-declined-{uuid4()}" gets a declined refund deterministically,
        # same mechanism as authorize()'s token markers.
        scenario = self._scenario_for(idempotency_key)
        if scenario == _DECLINED:
            return ProviderResult(
                outcome=ProviderOutcome.DECLINED,
                provider_transaction_id=provider_transaction_id,
                raw_status="refund_declined",
                raw_response={},
            )
        if scenario == _TEMPORARY_FAILURE:
            return ProviderResult(
                outcome=ProviderOutcome.TEMPORARY_FAILURE,
                provider_transaction_id=provider_transaction_id,
                raw_status="provider_unavailable",
                raw_response={},
            )
        if scenario in (_TIMEOUT, _UNKNOWN_RESULT, _STILL_UNKNOWN):
            return ProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                provider_transaction_id=provider_transaction_id,
                raw_status="no_response_received",
                raw_response={},
            )
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_transaction_id=provider_transaction_id,
            raw_status="refunded",
            raw_response={"amount_minor": amount_minor},
        )

    async def get_payment_status(self, provider_transaction_id: str) -> ProviderResult:
        for result in self._true_outcomes.values():
            if result.provider_transaction_id == provider_transaction_id:
                return result
        return ProviderResult(
            outcome=ProviderOutcome.UNKNOWN,
            provider_transaction_id=provider_transaction_id,
            raw_status="not_found",
            raw_response={},
        )

    async def get_payment_status_by_idempotency_key(self, idempotency_key: str) -> ProviderResult:
        true_result = self._true_outcomes.get(idempotency_key)
        if true_result is None:
            return ProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                provider_transaction_id=None,
                raw_status="not_found",
                raw_response={},
            )
        return true_result
