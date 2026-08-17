from __future__ import annotations

import json
import os

from domain.errors import PayGuardError
from fastapi import APIRouter, Depends, Header, Request
from webhooks.security import verify_webhook_signature
from webhooks.service import receive_webhook

from apps.api.dependencies import get_db_session

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


def _webhook_secret() -> str:
    # Single shared secret for the one MockProvider integration this project
    # has. A platform onboarding multiple real PSP accounts per merchant
    # would key this by (merchant_id, provider_name) instead -- noted as a
    # Phase 7 scope boundary in docs/webhooks.md, not an oversight.
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("WEBHOOK_SECRET is not set")
    return secret


@router.post("/provider", status_code=200)
async def receive_provider_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-PayGuard-Signature"),
    timestamp: str | None = Header(default=None, alias="X-PayGuard-Timestamp"),
    db_session=Depends(get_db_session),
) -> dict:
    raw_body = await request.body()

    # Verify over the raw bytes, before any JSON parsing -- see
    # packages/webhooks/security.py and docs/architecture.md section 11.
    verify_webhook_signature(
        secret=_webhook_secret(),
        timestamp_header=timestamp,
        signature_header=signature,
        raw_body=raw_body,
    )

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise PayGuardError("INVALID_REQUEST", "Webhook body is not valid JSON.") from exc

    provider_event_id = parsed.get("id")
    event_type = parsed.get("type")
    if not provider_event_id or not event_type:
        raise PayGuardError("INVALID_REQUEST", "Webhook body must include 'id' and 'type'.")

    await receive_webhook(
        db_session,
        provider_name="mock",
        provider_event_id=provider_event_id,
        event_type=event_type,
        raw_payload=parsed,
        signature=signature,
    )
    return {"received": True}
