"""Load test runner + report generator (Phase 15, product brief section 26).

Seeds a merchant, runs both k6 scenarios in loadtest/ against a live API
process the caller must already have running (`uvicorn apps.api.main:app`
or the dashboard's dev-server config), and prints a readable summary:
real p50/p95/p99 latency and error rate for the steady-throughput
scenario (parsed from k6's own JSON summary), and a direct Postgres query
proving the idempotency-storm scenario produced exactly one payment and
exactly one idempotency-key row despite 50 virtual users racing the same
key -- k6 itself only sees HTTP status codes, so the invariant that
actually matters is checked here, not in the k6 script.

Usage:
    docker compose up -d postgres redis
    alembic upgrade head
    uvicorn apps.api.main:app --port 8000   # in another terminal
    python scripts/run_load_test.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "packages"))

BASE_URL = "http://localhost:8000"


def _load_dotenv() -> None:
    import os

    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _find_k6() -> str:
    on_path = shutil.which("k6")
    if on_path:
        return on_path
    # winget/choco installs commonly land here without every shell's PATH
    # having been refreshed yet -- fall back rather than force the caller
    # to open a fresh terminal.
    fallback = pathlib.Path(r"C:\Program Files\k6\k6.exe")
    if fallback.exists():
        return str(fallback)
    raise SystemExit(
        "k6 not found on PATH or at the default Windows install location. "
        "Install it first: winget install --id=GrafanaLabs.k6 -e"
    )


def _banner(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


async def _seed_merchant() -> tuple[uuid.UUID, str]:
    from database.models import Merchant
    from database.session import get_sessionmaker
    from domain.security import generate_api_key, hash_api_key

    api_key = generate_api_key()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        merchant = Merchant(name="Load Test Merchant", api_key_hash=hash_api_key(api_key))
        session.add(merchant)
        await session.commit()
        return merchant.id, api_key


def _run_k6(script: str, k6_path: str, env: dict[str, str]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        summary_path = pathlib.Path(tmp) / "summary.json"
        args = [
            k6_path,
            "run",
            f"--summary-export={summary_path}",
            *[item for key, value in env.items() for item in ("-e", f"{key}={value}")],
            str(_ROOT / "loadtest" / script),
        ]
        result = subprocess.run(args, cwd=_ROOT, capture_output=False, check=False)
        if result.returncode not in (0, 99):  # 99 = k6 threshold breach, still produces a summary
            raise SystemExit(f"k6 run for {script} exited with an unexpected code {result.returncode}")
        return json.loads(summary_path.read_text())


def _print_latency_report(summary: dict) -> None:
    # k6 v2's --summary-export has no "values" wrapper -- every metric's
    # stats sit directly on the metric object (avg/min/med/max/p(90)/p(95)/
    # p(99) for a trend like http_req_duration, count/rate for a counter
    # like http_reqs, value for a rate metric like http_req_failed).
    metrics = summary.get("metrics", {})
    duration = metrics.get("http_req_duration", {})
    failed_rate = metrics.get("http_req_failed", {}).get("value", 0)
    reqs = metrics.get("http_reqs", {})

    print(f"  requests:        {reqs.get('count', '?')}")
    print(f"  throughput:      {reqs.get('rate', 0):.1f} req/s")
    print(f"  error rate:      {failed_rate * 100:.2f}%")
    print(f"  latency p50:     {duration.get('med', 0):.1f} ms")
    print(f"  latency p95:     {duration.get('p(95)', 0):.1f} ms")
    print(f"  latency p99:     {duration.get('p(99)', 0):.1f} ms")
    print(f"  latency max:     {duration.get('max', 0):.1f} ms")


async def _verify_idempotency_storm(merchant_id: uuid.UUID, idempotency_key: str) -> None:
    from database.models import IdempotencyKey, PaymentAttempt
    from database.session import get_sessionmaker
    from sqlalchemy import func, select

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        key_row_count = (
            await session.execute(
                select(func.count())
                .select_from(IdempotencyKey)
                .where(
                    IdempotencyKey.merchant_id == merchant_id,
                    IdempotencyKey.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()

        key_row = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.merchant_id == merchant_id,
                    IdempotencyKey.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()

        attempt_count = 0
        if key_row.payment_intent_id is not None:
            attempt_count = (
                await session.execute(
                    select(func.count())
                    .select_from(PaymentAttempt)
                    .where(PaymentAttempt.payment_intent_id == key_row.payment_intent_id)
                )
            ).scalar_one()

    print(f"  idempotency_keys rows for this key: {key_row_count} (must be exactly 1)")
    print(f"  payment_intent_id claimed:          {key_row.payment_intent_id}")
    print(f"  provider authorizations recorded:   {attempt_count} (must be exactly 1)")
    ok = key_row_count == 1 and attempt_count == 1
    print(f"  {'PASS' if ok else 'FAIL'}: 50 concurrent identical requests -> exactly one payment")


async def main() -> None:
    k6_path = _find_k6()
    print(f"using k6 at {k6_path}")

    merchant_id, api_key = await _seed_merchant()
    print(f"seeded merchant {merchant_id}")

    _banner("Steady-state throughput (ramping to 10 VUs)")
    steady_summary = _run_k6("steady_throughput.js", k6_path, {"BASE_URL": BASE_URL, "API_KEY": api_key})
    _print_latency_report(steady_summary)

    _banner("Idempotency storm (50 VUs, one shared Idempotency-Key)")
    idempotency_key = str(uuid.uuid4())
    _run_k6(
        "idempotency_storm.js",
        k6_path,
        {"BASE_URL": BASE_URL, "API_KEY": api_key, "IDEMPOTENCY_KEY": idempotency_key},
    )
    await _verify_idempotency_storm(merchant_id, idempotency_key)


if __name__ == "__main__":
    asyncio.run(main())
