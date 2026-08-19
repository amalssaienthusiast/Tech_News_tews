"""
[DEPRECATED] Tech News Scraper REST API v1.0

DEPRECATION NOTICE (Phase 8H Hardening):
This module represents the legacy unhardened API prototype.
It is superseded by the canonical production API:
  - Canonical API: src.api.app:app (invoked via `uvicorn src.api.app:app`)
"""

import logging
import time
import hashlib
import os
import warnings
from datetime import datetime, UTC
from typing import List, Optional
from functools import wraps

warnings.warn(
    "src/api/main.py is deprecated and will be removed in Phase 9. "
    "Use 'src.api.app:app' for the canonical API gateway.",
    DeprecationWarning,
    stacklevel=2,
)

from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# API CONFIGURATION
# =============================================================================

API_VERSION = "1.0.0"
API_TITLE = "Tech News Scraper API"
API_DESCRIPTION = """
## Overview
Enterprise-grade API for real-time tech news aggregation and analysis.

## Features
- 📰 **Articles**: Retrieve and search aggregated tech news
- 🔍 **Search**: Full-text search across all sources
- 📊 **Sentiment**: Real-time sentiment analysis and trends
- 🔔 **Webhooks**: Subscribe to real-time alerts (coming soon)

## Authentication
Include your API key in the `X-API-Key` header:
```
X-API-Key: your_api_key_here
```

## Rate Limits
| Tier | Requests/Day | Features |
|------|-------------|----------|
| Free | 100 | Basic articles |
| Pro | 10,000 | Full access |
| Enterprise | Unlimited | Priority + Webhooks |
"""

# API key tiers and limits
API_TIERS = {
    "free": {"daily_limit": 100, "features": ["articles"]},
    "pro": {"daily_limit": 10000, "features": ["articles", "search", "sentiment"]},
    "enterprise": {"daily_limit": float("inf"), "features": ["*"]},
}

# Security defaults can be relaxed explicitly for local development.
ALLOW_ANONYMOUS_API = os.getenv("API_ALLOW_ANONYMOUS", "false").lower() == "true"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("API_CORS_ORIGINS", "http://localhost,http://127.0.0.1").split(",")
    if origin.strip()
]


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class APIErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    message: str
    status_code: int


class ArticleResponse(BaseModel):
    """Single article response."""
    id: str
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    sentiment_score: Optional[float] = None
    topics: List[str] = []


class ArticlesListResponse(BaseModel):
    """List of articles response."""
    articles: List[ArticleResponse]
    total: int
    page: int
    per_page: int
    has_more: bool


class SentimentResponse(BaseModel):
    """Sentiment analysis response."""
    score: float = Field(description="Sentiment score from -1.0 to 1.0")
    label: str = Field(description="Sentiment label (positive/negative/neutral)")
    emoji: str
    topics: dict = {}
    keywords: List[str] = []


class TrendResponse(BaseModel):
    """Sentiment trend response."""
    topic: str
    period: str
    avg_score: float
    score_change: float
    article_count: int
    trend_direction: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: str
    database: str
    articles_count: int


# =============================================================================
# AUTHENTICATION & DEPENDENCIES (Imported from canonical src.api.auth)
# =============================================================================

from src.api.auth import (
    APIKeyManager,
    api_key_manager,
    rate_limiter,
    verify_api_key,
)


from contextlib import asynccontextmanager
from pathlib import Path
from src.api.routes.articles import router as articles_router, set_article_repository
from src.api.routes.events import router as events_router, set_event_repository
from src.api.routes.search import router as search_router
from src.api.routes.sentiment import router as sentiment_router
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import DEFAULT_CANONICAL_DB_PATH, SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path_env = os.getenv("TECHNEWS_CANONICAL_DB_PATH") or os.getenv("CANONICAL_DB_PATH")
    canonical_db_path = Path(db_path_env) if db_path_env else DEFAULT_CANONICAL_DB_PATH

    logger.info("Initializing canonical SQLite storage at %s", canonical_db_path)
    canonical_engine = SqliteEngine(canonical_db_path)
    await canonical_engine.initialize_schema()
    canonical_event_repo = SqliteEventRepository(engine=canonical_engine, auto_init=True)
    canonical_article_repo = SqliteArticleRepository(engine=canonical_engine, auto_init=True)

    set_event_repository(canonical_event_repo)
    set_article_repository(canonical_article_repo)
    app.state.canonical_engine = canonical_engine
    app.state.canonical_event_repository = canonical_event_repo
    app.state.canonical_article_repository = canonical_article_repo

    try:
        yield
    finally:
        logger.info("Shutting down %s", API_TITLE)
        set_event_repository(None)
        set_article_repository(None)
        if hasattr(app.state, "canonical_engine") and app.state.canonical_engine is not None:
            await app.state.canonical_engine.aclose()
            logger.info("Canonical SqliteEngine closed.")


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    process_time = time.time() - start
    response.headers["X-Process-Time"] = f"{process_time:.4f}"
    return response


# =============================================================================
# CORE ROUTER INCLUSIONS
# =============================================================================

app.include_router(events_router)
app.include_router(articles_router)
app.include_router(search_router)
app.include_router(sentiment_router)


@app.get("/", tags=["Info"])
async def root():
    """API root - basic info."""
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["Info"])
async def health_check():
    """Health check endpoint."""
    try:
        if hasattr(app.state, "canonical_article_repository") and app.state.canonical_article_repository is not None:
            count = await app.state.canonical_article_repository.count_articles()
            db_status = "connected"
        else:
            count = 0
            db_status = "connected"
    except Exception:
        count = 0
        db_status = "error"
    
    return HealthResponse(
        status="healthy",
        version=API_VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        database=db_status,
        articles_count=count,
    )


@app.get("/health/readiness", tags=["Monitoring"])
async def readiness_check():
    """
    Readiness check - is the application ready to accept traffic?
    
    Returns ready=true when database is connected and core components initialized.
    """
    try:
        from src.monitoring.health_check_endpoints import get_health_checker
        checker = get_health_checker()
        return await checker.check_readiness()
    except Exception as e:
        return {
            "status": "not_ready",
            "reason": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }


@app.get("/health/live", tags=["Monitoring"])
async def liveness_check():
    """
    Liveness probe for Kubernetes/Docker.

    Returns 200 OK if process is alive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/health/detailed", tags=["Monitoring"])
async def detailed_health():
    """
    Detailed health check - component-by-component status.
    
    Returns status of database, Redis, external APIs, LLM providers, and system resources.
    """
    try:
        from src.monitoring.health_check_endpoints import get_health_checker
        checker = get_health_checker()
        health = await checker.check_all()
        return health.to_dict()
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }


@app.get("/metrics", tags=["Monitoring"])
async def get_metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus text format for scraping.
    """
    from fastapi.responses import PlainTextResponse
    
    try:
        from src.monitoring.metrics_collector import get_metrics_collector
        collector = get_metrics_collector()
        metrics_output = collector.export_prometheus()
        return PlainTextResponse(content=metrics_output, media_type="text/plain")
    except Exception as e:
        return PlainTextResponse(
            content=f"# Error exporting metrics: {e}\n",
            media_type="text/plain"
        )


# =============================================================================
# APP FACTORY
# =============================================================================

def get_api_app() -> FastAPI:
    """Get the FastAPI app instance."""
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
