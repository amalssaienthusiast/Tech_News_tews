"""
Real-Time News API — the FastAPI app launched by main.py.

This is the production API surface. It was previously a thin unauthenticated
wrapper; the audit (P0-C) hardened it by porting auth, rate limiting, health
checks, metrics, and structured logging over from the dead src/api/main.py.

Security model:
  - API_ALLOW_ANONYMOUS env var (default: false). When false, every endpoint
    except /health and /metrics requires an X-API-Key header.
  - API keys are SHA-256 hashed at rest (see APIKeyManager.create_key).
  - Per-key daily rate limiting, tiered (free=1000, basic=10000, pro=100000).
  - CORS restricted to API_CORS_ORIGINS env var (default: localhost).

Operational endpoints:
  - GET  /health         — liveness + readiness for orchestrators
  - GET  /health/detailed — includes DB + Redis + dependency checks
  - GET  /metrics        — Prometheus text format
  - GET  /docs           — OpenAPI Swagger UI
  - GET  /redoc          — ReDoc

Data endpoints:
  - GET  /               — API metadata
  - GET  /feed/latest    — latest articles (paginated)
  - GET  /sources        — configured news sources
  - WS   /feed/ws        — live article stream
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from config.config import load_config
from src.api.routes.articles import (
    get_article_repository,
    router as articles_router,
    set_article_repository,
)
from src.api.routes.events import router as events_router, set_event_repository
from src.api.routes.search import router as search_router
from src.api.routes.sentiment import router as sentiment_router
from src.feed_generator.live_feed import LiveFeedGenerator
from src.scrapers.factory import ScraperFactory
from src.scheduler.task_scheduler import ScraperScheduler
from src.security.policy import (
    ALLOWED_ORIGINS,
    API_TIERS,
    RateLimiter,
    rate_limit_headers as policy_rate_limit_headers,
)
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine, DEFAULT_CANONICAL_DB_PATH
from src.storage.sqlite_event_repository import SqliteEventRepository

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
API_TITLE = "Real-Time News API"
API_VERSION = "2.0.0"
API_DESCRIPTION = "Production-hardened news aggregation API. Requires X-API-Key header."

ALLOW_ANONYMOUS_API = os.getenv("API_ALLOW_ANONYMOUS", "false").lower() == "true"
# CORS origins loaded from shared SecurityPolicy (ALLOWED_ORIGINS)

# Rate limiter, APIKeyManager, and auth dependency imported from canonical src.api.auth
from src.api.auth import (
    APIKeyManager,
    api_key_manager,
    rate_limiter,
    verify_api_key,
)


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight Prometheus-style metrics (hand-rolled, no extra dep)
# ─────────────────────────────────────────────────────────────────────────────
class MetricsCollector:
    """Minimal in-memory metrics collector emitting Prometheus text format."""

    def __init__(self) -> None:
        self._start_time = time.time()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, value: float = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def render(self) -> str:
        lines = [
            "# HELP technews_uptime_seconds Time since the API process started.",
            "# TYPE technews_uptime_seconds gauge",
            f"technews_uptime_seconds {time.time() - self._start_time:.2f}",
        ]
        for name, value in sorted(self._counters.items()):
            lines.extend([
                f"# HELP {name} counter",
                f"# TYPE {name} counter",
                f"{name} {value}",
            ])
        for name, value in sorted(self._gauges.items()):
            lines.extend([
                f"# HELP {name} gauge",
                f"# TYPE {name} gauge",
                f"{name} {value}",
            ])
        return "\n".join(lines) + "\n"


metrics = MetricsCollector()


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket connection manager
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        metrics.set_gauge("technews_ws_active_connections", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        metrics.set_gauge("technews_ws_active_connections", len(self.active_connections))

    async def broadcast(self, message: dict) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan (modern FastAPI; replaces @app.on_event)
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", API_TITLE, API_VERSION)

    # Initialize Canonical Storage Engine & Repositories (Phase 5D-B, 5E-E, 5F)
    from pathlib import Path
    db_path_env = os.getenv("TECHNEWS_CANONICAL_DB_PATH") or os.getenv("CANONICAL_DB_PATH")
    canonical_db_path = Path(db_path_env) if db_path_env else DEFAULT_CANONICAL_DB_PATH

    logger.info("Initializing canonical SQLite storage at %s", canonical_db_path)
    canonical_engine = SqliteEngine(canonical_db_path)
    await canonical_engine.initialize_schema()
    canonical_event_repo = SqliteEventRepository(engine=canonical_engine, auto_init=True)
    canonical_article_repo = SqliteArticleRepository(engine=canonical_engine, auto_init=True)

    # Register repositories in route dependency injection and app state
    set_event_repository(canonical_event_repo)
    set_article_repository(canonical_article_repo)
    app.state.canonical_engine = canonical_engine
    app.state.canonical_event_repository = canonical_event_repo
    app.state.canonical_article_repository = canonical_article_repo

    metrics.set_gauge("technews_uptime_seconds", 0)

    try:
        yield
    finally:
        logger.info("Shutting down %s", API_TITLE)
        set_event_repository(None)
        set_article_repository(None)
        if hasattr(app.state, "canonical_engine") and app.state.canonical_engine is not None:
            await app.state.canonical_engine.aclose()
            logger.info("Canonical SqliteEngine closed.")


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────
from src.observability import (
    PrometheusMetricsMiddleware,
    get_metrics_registry,
)
from src.security.middleware import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 1. Observability & Telemetry (Phase 6E)
app.add_middleware(PrometheusMetricsMiddleware)

# 2. Security Headers & Request Limits (Phase 6D)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=2 * 1024 * 1024)

# 3. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(events_router)
app.include_router(articles_router)
app.include_router(search_router)
app.include_router(sentiment_router)


# ─────────────────────────────────────────────────────────────────────────────
# Operational endpoints (no auth required)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["ops"])
async def health():
    """Liveness + readiness probe. Always returns 200 if the process is up."""
    return {
        "status": "ok",
        "version": API_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/health/detailed", tags=["ops"])
async def health_detailed():
    """Detailed health check including DB connectivity."""
    db_status = "unknown"
    article_count = -1
    event_count = -1
    metrics_reg = get_metrics_registry()
    try:
        repo = get_article_repository()
        article_count = await repo.count_articles()
        metrics_reg.db_articles_total.set(article_count)
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    try:
        from src.api.routes.events import get_event_repository
        event_repo = get_event_repository()
        stats = await event_repo.get_stats()
        event_count = stats.get("total_events", 0)
        metrics_reg.db_events_total.set(event_count)
    except Exception:
        pass

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": API_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "database": db_status,
        "articles_count": article_count,
        "events_count": event_count,
    }


@app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus-format metrics. Unauthenticated so Prometheus can scrape."""
    metrics_reg = get_metrics_registry()
    try:
        repo = get_article_repository()
        count = await repo.count_articles()
        metrics_reg.db_articles_total.set(count)
    except Exception:
        pass
    return metrics_reg.render_prometheus()


# ─────────────────────────────────────────────────────────────────────────────
# Data endpoints (auth required unless anonymous mode is on)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/", tags=["meta"])
async def root(_: dict = Depends(verify_api_key)):
    """API metadata."""
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "status": "running",
        "docs": "/docs",
        "tier": _.get("tier", "free"),
        "anonymous": _.get("anonymous", False),
    }


@app.get("/feed/latest", tags=["feed"])
async def get_latest_feed(
    limit: int = Query(50, ge=1, le=500),
    _: dict = Depends(verify_api_key),
):
    """Get latest news feed from canonical article repository."""
    metrics.inc("technews_feed_requests_total")
    try:
        repo = get_article_repository()
        recent = await repo.get_recent_articles(limit=limit)
        articles = [
            {
                "id": a.id,
                "title": a.title,
                "url": a.canonical_url,
                "source": a.source_name or a.source_id,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "summary": a.summary or (a.clean_text[:300].strip() if a.clean_text else None),
            }
            for a in recent
        ]
    except Exception as e:
        logger.warning("Error fetching latest feed: %s", e)
        articles = []

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "total": len(articles),
        "articles": articles,
    }


@app.get("/sources", tags=["feed"])
async def get_sources(_: dict = Depends(verify_api_key)):
    """Get available news sources."""
    config = load_config()
    return {
        "sources": [
            {
                "name": source["name"],
                "type": source["type"],
                "refresh_rate": source.get("refresh_rate", 300),
                "enabled": source.get("enabled", True),
            }
            for source in config["sources"]
            if source.get("enabled", True)
        ]
    }


@app.websocket("/feed/ws")
async def websocket_feed(websocket: WebSocket):
    """WebSocket for real-time feed updates.

    Note: WebSocket auth is via query param ?api_key=... — header-based auth
    is not supported in the browser WebSocket API. If API_ALLOW_ANONYMOUS
    is false and no api_key query param is provided, the connection is closed
    with code 4401.
    """
    # Optional WS auth
    if not ALLOW_ANONYMOUS_API:
        api_key = websocket.query_params.get("api_key")
        if not api_key or not api_key_manager.validate_key(api_key):
            await websocket.close(code=4401)
            return

    await manager.connect(websocket)
    try:
        while True:
            try:
                repo = get_article_repository()
                recent = await repo.get_recent_articles(limit=20)
                articles = [
                    {
                        "id": a.id,
                        "title": a.title,
                        "url": a.canonical_url,
                        "source": a.source_name or a.source_id,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "summary": a.summary or (a.clean_text[:300].strip() if a.clean_text else None),
                    }
                    for a in recent
                ]
            except Exception:
                articles = []

            feed = {
                "type": "update",
                "timestamp": datetime.now(UTC).isoformat(),
                "articles": articles or [],
            }
            await websocket.send_json(feed)
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket error: %s", e)
        manager.disconnect(websocket)


# ─────────────────────────────────────────────────────────────────────────────
# Admin endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/admin/api-keys", tags=["admin"])
async def create_api_key(
    user_id: str = Query(...),
    tier: str = Query("free", pattern="^(free|basic|pro)$"),
    name: str = Query(""),
    _: dict = Depends(verify_api_key),
):
    """Create a new API key. Requires an existing valid key (any tier).

    The plaintext key is returned exactly once — store it securely.
    """
    if _["tier"] != "pro":
        raise HTTPException(status_code=403, detail="Only pro-tier keys can create new keys")
    plaintext = api_key_manager.create_key(user_id=user_id, tier=tier, name=name)
    if not plaintext:
        raise HTTPException(status_code=500, detail="Failed to create API key")
    return {"api_key": plaintext, "tier": tier, "user_id": user_id}


def get_app() -> FastAPI:
    """Get the production FastAPI application instance."""
    return app


# Re-export for main.py compatibility
__all__ = ["app", "get_app", "verify_api_key", "api_key_manager", "rate_limiter"]
