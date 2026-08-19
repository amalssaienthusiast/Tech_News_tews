# Multi-Stage Production Dockerfile for Tech News Scrapper
# Build Stage
FROM python:3.12-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml requirements.txt README.md /build/
COPY src/ /build/src/
COPY config/ /build/config/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt .

# Runtime Stage
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TECHNEWS_DATA_DIR=/data \
    TECHNEWS_PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root security user
RUN groupadd -r technews && useradd -r -g technews -d /app -s /sbin/nologin technews
RUN mkdir -p /app /data && chown -R technews:technews /app /data

WORKDIR /app
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY --chown=technews:technews src/ /app/src/
COPY --chown=technews:technews config/ /app/config/
COPY --chown=technews:technews scripts/ /app/scripts/
COPY --chown=technews:technews pyproject.toml README.md /app/

USER technews

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
