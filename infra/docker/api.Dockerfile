# Multi-stage build (Phase 17): the builder stage has the full toolchain
# needed to resolve and install dependencies; the runtime stage copies only
# the resulting site-packages and application code, so the shipped image
# doesn't carry a C compiler or pip's own cache around for no reason.
FROM python:3.12-slim AS builder

WORKDIR /build

# --no-install-recommends keeps this to exactly what asyncpg's C extension
# needs to build, not the full recommended set apt would otherwise pull in.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY packages ./packages

# Installed into a venv (not system site-packages) purely so the whole
# directory can be copied into the runtime stage as one unit -- copying
# scattered system site-packages paths is harder to get right than copying
# one self-contained /opt/venv.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

# libpq5 is asyncpg's actual runtime dependency; libpq-dev (with the headers
# and pg_config the build stage needed) never ships here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 payguard

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY apps/api ./apps/api
COPY apps/__init__.py ./apps/__init__.py
COPY packages ./packages
COPY alembic.ini ./

USER payguard
EXPOSE 8000

# No shell-form CMD and no reload flag: this is the production entrypoint,
# not the dev-server config in .claude/launch.json.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
