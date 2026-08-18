from __future__ import annotations

import os
import pathlib
import uuid


def _load_dotenv() -> None:
    # Mirrors apps/worker/main.py and scripts/seed_merchant.py -- the API
    # must be runnable standalone (e.g. `uvicorn apps.api.main:app`) without
    # requiring the caller to have exported .env into the shell first.
    env_path = pathlib.Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

from database.session import get_engine  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from providers import MockProvider  # noqa: E402
from sqlalchemy import text  # noqa: E402

from apps.api.errors import install_error_handlers  # noqa: E402
from apps.api.routers import payments, refunds, webhooks  # noqa: E402

app = FastAPI(title="PayGuard API", version="0.1.0")
install_error_handlers(app)
app.include_router(payments.router)
app.include_router(refunds.router)
app.include_router(webhooks.router)

# MockProvider holds no I/O resources (its "connection" is an in-memory
# dict), so it needs no async startup/shutdown -- a plain module-level
# instance avoids relying on the ASGI lifespan protocol firing, which isn't
# guaranteed under every test transport.
app.state.provider = MockProvider()


@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    request.state.request_id = f"req_{uuid.uuid4().hex}"
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.get("/v1/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/ready")
async def ready() -> dict:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready"}
