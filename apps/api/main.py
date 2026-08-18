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
from fastapi import FastAPI, Request, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from observability import (  # noqa: E402
    bind_context,
    configure_logging,
    configure_tracing,
    get_tracer,
    render_latest,
)
from providers import MockProvider  # noqa: E402
from sqlalchemy import text  # noqa: E402

from apps.api.errors import install_error_handlers  # noqa: E402
from apps.api.routers import dashboard, payments, refunds, webhooks  # noqa: E402

configure_logging()
configure_tracing()
_tracer = get_tracer("payguard.api")

app = FastAPI(title="PayGuard API", version="0.1.0")
install_error_handlers(app)
# The dashboard (Phase 13) is a separate origin (Vite dev server / static
# build) calling this API with a bearer API key, never a cookie -- so this
# is safe to scope wide open on origins without also enabling credentialed
# requests. A real deployment would replace "*" with the dashboard's actual
# origin(s); nothing here trusts the browser's origin for authorization.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(payments.router)
app.include_router(refunds.router)
app.include_router(webhooks.router)
app.include_router(dashboard.router)

# MockProvider holds no I/O resources (its "connection" is an in-memory
# dict), so it needs no async startup/shutdown -- a plain module-level
# instance avoids relying on the ASGI lifespan protocol firing, which isn't
# guaranteed under every test transport.
app.state.provider = MockProvider()


@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    request_id = f"req_{uuid.uuid4().hex}"
    request.state.request_id = request_id
    # Every log line and every child span emitted anywhere during this
    # request's handling -- including deep inside packages/payments,
    # packages/webhooks, etc. -- automatically carries request_id, without
    # any of those modules importing anything request-scoped.
    with (
        bind_context(request_id=request_id),
        _tracer.start_as_current_span(
            "http.request",
            attributes={"http.method": request.method, "http.path": request.url.path},
        ),
    ):
        response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.get("/v1/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/ready")
async def ready() -> dict:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
