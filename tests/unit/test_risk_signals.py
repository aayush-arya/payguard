"""Unit tests for the pure, synchronous risk signal helpers -- no database
needed, since these signals depend only on their inputs (product brief
section 20: deterministic and explainable)."""

import pytest
from risk.service import (
    BLOCK_THRESHOLD,
    HIGH_THRESHOLD,
    LARGE_AMOUNT_THRESHOLD_MINOR,
    MEDIUM_THRESHOLD,
    VERY_LARGE_AMOUNT_THRESHOLD_MINOR,
    RiskLevel,
    _amount_signal,
    _country_mismatch_signal,
    _high_risk_ip_signal,
    _level_for_score,
)


def test_small_amount_has_no_signal():
    assert _amount_signal(100) is None


def test_large_amount_signal_fires_at_threshold():
    signal = _amount_signal(LARGE_AMOUNT_THRESHOLD_MINOR)
    assert signal is not None
    assert signal.name == "LARGE_AMOUNT"


def test_very_large_amount_supersedes_large_not_both():
    signal = _amount_signal(VERY_LARGE_AMOUNT_THRESHOLD_MINOR)
    assert signal is not None
    assert signal.name == "VERY_LARGE_AMOUNT"  # only one signal, not both tiers stacking


def test_country_mismatch_requires_both_present():
    assert _country_mismatch_signal(None, "US") is None
    assert _country_mismatch_signal("US", None) is None
    assert _country_mismatch_signal(None, None) is None


def test_country_mismatch_fires_on_difference():
    signal = _country_mismatch_signal("US", "RU")
    assert signal is not None
    assert signal.name == "BILLING_SHIPPING_COUNTRY_MISMATCH"


def test_country_match_has_no_signal():
    assert _country_mismatch_signal("US", "US") is None


def test_high_risk_ip_signal_fires_for_reserved_test_range():
    signal = _high_risk_ip_signal("203.0.113.42")
    assert signal is not None
    assert signal.name == "HIGH_RISK_IP"


def test_ordinary_ip_has_no_signal():
    assert _high_risk_ip_signal("8.8.8.8") is None


def test_missing_ip_has_no_signal():
    assert _high_risk_ip_signal(None) is None


@pytest.mark.parametrize(
    "score,expected",
    [
        (0, RiskLevel.LOW),
        (MEDIUM_THRESHOLD - 1, RiskLevel.LOW),
        (MEDIUM_THRESHOLD, RiskLevel.MEDIUM),
        (HIGH_THRESHOLD - 1, RiskLevel.MEDIUM),
        (HIGH_THRESHOLD, RiskLevel.HIGH),
        (BLOCK_THRESHOLD - 1, RiskLevel.HIGH),
        (BLOCK_THRESHOLD, RiskLevel.BLOCK),
        (BLOCK_THRESHOLD + 1000, RiskLevel.BLOCK),
    ],
)
def test_level_thresholds(score, expected):
    assert _level_for_score(score) is expected
