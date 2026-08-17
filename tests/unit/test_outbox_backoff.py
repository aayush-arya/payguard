from datetime import timedelta

import pytest
from outbox.worker import BASE_DELAY_SECONDS, MAX_ATTEMPTS, MAX_DELAY_SECONDS, compute_backoff


@pytest.mark.parametrize("attempt_count", range(1, 12))
def test_backoff_never_exceeds_the_cap(attempt_count):
    delay = compute_backoff(attempt_count)
    assert timedelta(0) <= delay <= timedelta(seconds=MAX_DELAY_SECONDS)


def test_backoff_grows_with_attempt_count_on_average():
    """Full jitter means any single sample can be small, but the expected
    (average) delay should still climb with attempt_count until it saturates
    at the cap -- sample many draws to smooth out jitter noise."""
    samples = 500

    def average_delay(attempt_count: int) -> float:
        return sum(compute_backoff(attempt_count).total_seconds() for _ in range(samples)) / samples

    early = average_delay(1)
    later = average_delay(4)
    assert later > early


def test_backoff_saturates_at_max_delay_for_large_attempt_counts():
    # 2**(20-1) * BASE_DELAY_SECONDS is astronomically larger than the cap.
    delay = compute_backoff(20)
    assert delay <= timedelta(seconds=MAX_DELAY_SECONDS)


def test_first_attempt_backoff_is_bounded_by_base_delay():
    delay = compute_backoff(1)
    assert delay <= timedelta(seconds=BASE_DELAY_SECONDS)


def test_max_attempts_is_a_small_positive_bound():
    # Sanity check on the constant itself: dead-lettering must actually be
    # reachable in finite retries, not effectively infinite.
    assert 1 <= MAX_ATTEMPTS <= 20
