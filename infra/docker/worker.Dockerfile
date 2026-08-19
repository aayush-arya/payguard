# Mirrors infra/docker/api.Dockerfile's build -- same dependency set (the
# worker imports the same packages/* the API does), different entrypoint
# and no exposed port, since nothing calls the worker over HTTP.
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY packages ./packages

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 payguard

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY apps/worker ./apps/worker
COPY apps/__init__.py ./apps/__init__.py
COPY packages ./packages

USER payguard

CMD ["python", "apps/worker/main.py"]
