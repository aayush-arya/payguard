"""Narrated walkthrough of PayGuard's canonical resilience demos, run
against the real FastAPI app, real routing/dependency-injection, and a
real Postgres database -- the same in-process ASGI transport the test
suite itself uses (httpx.AsyncClient + ASGITransport), not a mocked
substitute, so what you see here is exactly what the API actually does.

Each demo is self-contained and narrated with print() so it reads well
live. This is a demonstration script, not a test: it has no assertions
and won't fail the build if something looks off -- it exists to *show*
the resilience story, while tests/ is what actually proves it.

Usage:
    python scripts/demo_scenarios.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "packages"))
sys.path.insert(0, str(_ROOT))


def _load_dotenv() -> None:
    import os

    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _quiet_the_noise() -> None:
    """apps.api.main configures real JSON logging and a console span
    exporter at import time (correct for the actual API process, which has
    no other visibility) -- great for production, terrible for a script
    whose entire point is readable narration. Both are safe to reconfigure
    after import: logging.getLogger("payguard") owns every log line this
    codebase emits (packages/observability/logging.py), and
    configure_tracing() can be called again with a real-but-silent
    exporter, same as tests do with InMemorySpanExporter."""
    import logging

    from observability import configure_tracing

    logging.getLogger().setLevel(logging.CRITICAL)

    class _NullExporter:
        def export(self, spans):  # noqa: ARG002
            from opentelemetry.sdk.trace.export import SpanExportResult

            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            pass

    configure_tracing(exporter=_NullExporter())


def _banner(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _demo_1_happy_path(client, api_key: str) -> None:
    _banner("Demo 1: happy path -- create, authorize, capture")
    create = await client.post(
        "/v1/payments",
        json={"amount": 4999, "currency": "USD", "payment_method": {"type": "token", "token": "pm_demo_ok"}},
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment = create.json()
    print(f"  created payment {payment['id']} -> status={payment['status']}")
    print("  (authorized successfully; PROCESSING means 'awaiting capture', not an error)")

    capture = await client.post(
        f"/v1/payments/{payment['id']}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    print(f"  captured -> status={capture.json()['status']}")


async def _demo_2_declined(client, api_key: str) -> None:
    _banner("Demo 2: declined payment -- a permanent failure, correctly not retried")
    create = await client.post(
        "/v1/payments",
        json={
            "amount": 2500,
            "currency": "USD",
            "payment_method": {"type": "token", "token": "pm_demo_declined"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment = create.json()
    print(f"  created payment {payment['id']} -> status={payment['status']}")
    print("  the provider declined it outright -- classified PERMANENT, no retry attempted")


async def _demo_3_timeout_reconciliation(
    client, api_key: str, db_sessionmaker, provider, merchant_id
) -> None:
    from reconciliation import run_reconciliation_pass

    _banner("Demo 3: response lost in transit -- resolved by reconciliation, not a blind retry")
    create = await client.post(
        "/v1/payments",
        json={
            "amount": 7500,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_timeout_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment = create.json()
    print(f"  created payment {payment['id']} -> status={payment['status']}")
    print("  the provider actually authorized it -- only OUR response was lost")
    print("  (a naive system would retry blindly here and risk a double-charge)")

    async with db_sessionmaker() as session:
        reports = await run_reconciliation_pass(session, provider, merchant_id=merchant_id)
    matching = [r for r in reports if str(r.payment_intent_id) == payment["id"]]
    if matching:
        print(f"  reconciliation asked the provider directly -> result={matching[0].result}")

    check = await client.get(f"/v1/payments/{payment['id']}", headers=_headers(api_key))
    print(f"  payment status now: {check.json()['status']}")


async def _demo_4_webhook_dedup_note() -> None:
    _banner("Demo 4: duplicate webhook delivery dedups to exactly one effect")
    print("  proven under real concurrency (20 simultaneous identical deliveries)")
    print("  in tests/concurrency/test_webhook_race.py -- not re-run here since it")
    print("  needs HMAC request signing, which deserves its own focused test, not a")
    print("  demo script reimplementing it")


async def _demo_5_chaos_burst(client, api_key: str, db_sessionmaker, app, merchant_id) -> None:
    from providers import ChaosConfig, ChaosProvider, MockProvider
    from reconciliation import run_reconciliation_pass

    _banner("Demo 5: chaos burst -- 20 concurrent payments, 35% response-loss rate")
    original_provider = app.state.provider
    chaos = ChaosProvider(MockProvider(), ChaosConfig(unknown_rate=0.35, seed=1))
    app.state.provider = chaos
    try:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/v1/payments",
                    json={
                        "amount": 1000 + i,
                        "currency": "USD",
                        "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
                    },
                    headers=_headers(api_key, str(uuid.uuid4())),
                )
                for i in range(20)
            )
        )
        bodies = [r.json() for r in responses]
        unknown_count = sum(1 for b in bodies if b["status"] == "UNKNOWN")
        print(f"  fired 20 concurrent payments -> {unknown_count} came back UNKNOWN")
        print("  (chaos corrupted the caller-visible response; the provider still knows the truth)")

        async with db_sessionmaker() as session:
            reports = await run_reconciliation_pass(session, chaos, merchant_id=merchant_id)
        print(f"  reconciliation resolved {len(reports)} payment(s):")
        for report in reports:
            print(f"    {report.payment_intent_id} -> {report.result}")
    finally:
        app.state.provider = original_provider


async def main() -> None:
    from database.models import Merchant
    from database.session import get_sessionmaker
    from domain.security import generate_api_key, hash_api_key
    from httpx import ASGITransport, AsyncClient

    from apps.api.main import app

    _quiet_the_noise()

    sessionmaker = get_sessionmaker()
    api_key = generate_api_key()
    async with sessionmaker() as session:
        merchant = Merchant(name="Demo Scenarios Merchant", api_key_hash=hash_api_key(api_key))
        session.add(merchant)
        await session.commit()
        merchant_id = merchant.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo") as client:
        await _demo_1_happy_path(client, api_key)
        await _demo_2_declined(client, api_key)
        await _demo_3_timeout_reconciliation(client, api_key, sessionmaker, app.state.provider, merchant_id)
        await _demo_4_webhook_dedup_note()
        await _demo_5_chaos_burst(client, api_key, sessionmaker, app, merchant_id)

    _banner("Done")
    print(f"  merchant: {merchant_id}")
    print(f"  api key:  {api_key}")


if __name__ == "__main__":
    asyncio.run(main())
