"""Webhook signature verification (ADR-006, docs/architecture.md section 13).

Threat model: the webhook endpoint is public and unauthenticated by any means
except this signature. Anyone can POST to it. The only thing separating a
real provider notification from an attacker-forged one is proof of
possession of the shared secret, demonstrated via HMAC-SHA256 over the raw
request body plus a timestamp.

Verification happens over the *raw* body bytes, before any JSON parsing.
Parsing then re-serializing to verify would let key reordering, whitespace,
or number formatting differences silently break (or worse, spoof) the
signature -- see docs/architecture.md section 11.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from domain.errors import PayGuardError

DEFAULT_TOLERANCE_SECONDS = 300  # 5 minutes


def sign_payload(secret: str, timestamp: str, raw_body: bytes) -> str:
    signed_payload = timestamp.encode() + b"." + raw_body
    return hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    *,
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
    raw_body: bytes,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
) -> None:
    """Raises PayGuardError("WEBHOOK_SIGNATURE_INVALID", ...) on any failure.
    There is no partial-trust return value -- a webhook is either verified or
    rejected, nothing in between reaches the caller.
    """
    if not timestamp_header or not signature_header:
        raise PayGuardError("WEBHOOK_SIGNATURE_INVALID", "Missing signature or timestamp header.")

    try:
        timestamp = int(timestamp_header)
    except ValueError:
        raise PayGuardError("WEBHOOK_SIGNATURE_INVALID", "Malformed timestamp header.") from None

    # Replay protection: a signature captured off the wire and replayed later
    # is only valid within this window, even though the HMAC itself would
    # still check out -- the timestamp is part of what's signed.
    now = int(time.time())
    if abs(now - timestamp) > tolerance_seconds:
        raise PayGuardError(
            "WEBHOOK_SIGNATURE_INVALID", "Webhook timestamp is outside the allowed tolerance window."
        )

    expected_signature = sign_payload(secret, timestamp_header, raw_body)
    # Constant-time comparison: a naive `==` leaks timing information an
    # attacker could use to guess the signature byte-by-byte.
    if not hmac.compare_digest(expected_signature, signature_header):
        raise PayGuardError("WEBHOOK_SIGNATURE_INVALID", "Signature verification failed.")
