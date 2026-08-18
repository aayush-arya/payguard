"""Unit tests for ChaosProvider (Phase 14): proves corruption is applied at
the right rate, is reproducible under a fixed seed, and never destroys the
wrapped provider's ability to reveal the truth later -- the property
reconciliation depends on."""

import time
import uuid

import pytest
from providers.base import AuthorizeRequest, ProviderOutcome
from providers.chaos import ChaosConfig, ChaosProvider
from providers.mock import MockProvider


def _request(idempotency_key: str | None = None) -> AuthorizeRequest:
    return AuthorizeRequest(
        amount_minor=1000,
        currency="USD",
        token="pm_demo_ok",
        idempotency_key=idempotency_key or str(uuid.uuid4()),
    )


async def test_unknown_rate_zero_is_exact_passthrough():
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(unknown_rate=0.0))
    result = await chaos.authorize(_request())
    assert result.outcome is ProviderOutcome.SUCCEEDED


async def test_unknown_rate_one_always_corrupts_the_caller_visible_outcome():
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(unknown_rate=1.0))
    result = await chaos.authorize(_request())
    assert result.outcome is ProviderOutcome.UNKNOWN
    assert result.provider_transaction_id is None


async def test_corruption_does_not_destroy_the_true_outcome():
    """The property reconciliation depends on: even though the caller sees
    UNKNOWN, asking the wrapped provider directly (as reconciliation does)
    still reveals what really happened."""
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(unknown_rate=1.0))
    key = str(uuid.uuid4())
    result = await chaos.authorize(_request(key))
    assert result.outcome is ProviderOutcome.UNKNOWN

    truth = await chaos.get_payment_status_by_idempotency_key(key)
    assert truth.outcome is ProviderOutcome.SUCCEEDED
    assert truth.provider_transaction_id is not None


async def test_same_seed_produces_the_same_sequence_of_decisions():
    key = str(uuid.uuid4())
    config = ChaosConfig(unknown_rate=0.5, seed=42)

    chaos_a = ChaosProvider(MockProvider(), config)
    chaos_b = ChaosProvider(MockProvider(), config)

    outcomes_a = [(await chaos_a.authorize(_request(f"{key}-{i}"))).outcome for i in range(20)]
    outcomes_b = [(await chaos_b.authorize(_request(f"{key}-{i}"))).outcome for i in range(20)]

    assert outcomes_a == outcomes_b
    # Not a degenerate all-same-outcome run -- proves the rate is actually
    # being exercised, not accidentally always 0 or always 1.
    assert ProviderOutcome.UNKNOWN in outcomes_a
    assert ProviderOutcome.SUCCEEDED in outcomes_a


async def test_slow_rate_actually_delays():
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(slow_rate=1.0, slow_delay_seconds=0.05))
    start = time.perf_counter()
    await chaos.authorize(_request())
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.05


async def test_slow_rate_zero_adds_no_delay():
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(slow_rate=0.0, slow_delay_seconds=5.0))
    start = time.perf_counter()
    await chaos.authorize(_request())
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0


async def test_capture_and_refund_pass_through_uncorrupted():
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(unknown_rate=1.0))

    key = str(uuid.uuid4())
    authorize_result = await chaos.authorize(_request(key))
    assert authorize_result.outcome is ProviderOutcome.UNKNOWN
    truth = await inner.get_payment_status_by_idempotency_key(key)
    assert truth.outcome is ProviderOutcome.SUCCEEDED

    capture_result = await chaos.capture("ptx_whatever", 1000)
    assert capture_result.outcome is ProviderOutcome.SUCCEEDED

    refund_result = await chaos.refund("ptx_whatever", 1000, str(uuid.uuid4()))
    assert refund_result.outcome is ProviderOutcome.SUCCEEDED


@pytest.mark.parametrize("rate", [0.0, 1.0])
async def test_get_payment_status_is_never_corrupted(rate):
    inner = MockProvider()
    chaos = ChaosProvider(inner, ChaosConfig(unknown_rate=rate))
    key = str(uuid.uuid4())
    await chaos.authorize(_request(key))
    result = await chaos.get_payment_status_by_idempotency_key(key)
    assert result.outcome is ProviderOutcome.SUCCEEDED
