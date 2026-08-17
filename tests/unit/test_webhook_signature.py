import time

import pytest
from domain.errors import PayGuardError
from webhooks.security import sign_payload, verify_webhook_signature

SECRET = "test_secret"
BODY = b'{"id":"evt_1","type":"payment.succeeded"}'


def _valid_headers(secret: str = SECRET, body: bytes = BODY) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    signature = sign_payload(secret, timestamp, body)
    return timestamp, signature


def test_valid_signature_passes():
    timestamp, signature = _valid_headers()
    verify_webhook_signature(
        secret=SECRET, timestamp_header=timestamp, signature_header=signature, raw_body=BODY
    )  # must not raise


def test_missing_signature_header_is_rejected():
    timestamp, _ = _valid_headers()
    with pytest.raises(PayGuardError) as exc_info:
        verify_webhook_signature(
            secret=SECRET, timestamp_header=timestamp, signature_header=None, raw_body=BODY
        )
    assert exc_info.value.code == "WEBHOOK_SIGNATURE_INVALID"


def test_missing_timestamp_header_is_rejected():
    _, signature = _valid_headers()
    with pytest.raises(PayGuardError) as exc_info:
        verify_webhook_signature(
            secret=SECRET, timestamp_header=None, signature_header=signature, raw_body=BODY
        )
    assert exc_info.value.code == "WEBHOOK_SIGNATURE_INVALID"


def test_malformed_timestamp_is_rejected():
    _, signature = _valid_headers()
    with pytest.raises(PayGuardError):
        verify_webhook_signature(
            secret=SECRET, timestamp_header="not-a-number", signature_header=signature, raw_body=BODY
        )


def test_wrong_secret_is_rejected():
    timestamp = str(int(time.time()))
    signature = sign_payload("a-different-secret", timestamp, BODY)
    with pytest.raises(PayGuardError):
        verify_webhook_signature(
            secret=SECRET, timestamp_header=timestamp, signature_header=signature, raw_body=BODY
        )


def test_tampered_body_is_rejected():
    """The signature must cover the raw body -- if a byte changes after
    signing, verification must fail even though the signature string itself
    is well-formed and was genuinely produced by sign_payload."""
    timestamp = str(int(time.time()))
    signature = sign_payload(SECRET, timestamp, BODY)
    tampered_body = BODY.replace(b"payment.succeeded", b"payment.failed  ")
    with pytest.raises(PayGuardError):
        verify_webhook_signature(
            secret=SECRET, timestamp_header=timestamp, signature_header=signature, raw_body=tampered_body
        )


def test_stale_timestamp_outside_tolerance_is_rejected():
    """Replay protection: a captured, genuinely-valid signature from too
    long ago must not verify, even against the same body and secret."""
    old_timestamp = str(int(time.time()) - 3600)
    signature = sign_payload(SECRET, old_timestamp, BODY)
    with pytest.raises(PayGuardError):
        verify_webhook_signature(
            secret=SECRET,
            timestamp_header=old_timestamp,
            signature_header=signature,
            raw_body=BODY,
            tolerance_seconds=300,
        )


def test_timestamp_within_tolerance_passes():
    recent_timestamp = str(int(time.time()) - 60)
    signature = sign_payload(SECRET, recent_timestamp, BODY)
    verify_webhook_signature(
        secret=SECRET,
        timestamp_header=recent_timestamp,
        signature_header=signature,
        raw_body=BODY,
        tolerance_seconds=300,
    )  # must not raise


def test_future_timestamp_outside_tolerance_is_rejected():
    """Tolerance is symmetric -- a timestamp implausibly far in the future
    is just as suspicious as one far in the past."""
    future_timestamp = str(int(time.time()) + 3600)
    signature = sign_payload(SECRET, future_timestamp, BODY)
    with pytest.raises(PayGuardError):
        verify_webhook_signature(
            secret=SECRET,
            timestamp_header=future_timestamp,
            signature_header=signature,
            raw_body=BODY,
            tolerance_seconds=300,
        )
