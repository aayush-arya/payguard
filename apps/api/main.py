from __future__ import annotations

import uuid

from database.session import get_engine
from fastapi import FastAPI, Request
from providers import MockProvider
from sqlalchemy import text

from apps.api.errors import install_error_handlers
from apps.api.routers import payments, webhooks

app = FastAPI(title="PayGuard API", version="0.1.0")
install_error_handlers(app)
app.include_router(payments.router)
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
