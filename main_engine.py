#!/usr/bin/env python3
"""
[DEPRECATED] Main Engine Server — Legacy monolithic aiohttp engine.

DEPRECATION NOTICE (Phase 8H Hardening):
This server combines a legacy aiohttp server on port 8080 with in-memory ring buffers.
It is superseded by the canonical production architecture:
  - Canonical API:            uvicorn src.api.app:app --port 8000
  - Canonical Ingestion Worker: python -m src.worker
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import warnings
import signal
import sys
import time
from collections import deque
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

import aiohttp
from aiohttp import web

# Ensure project root on sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env
env_path = ROOT_DIR / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip("'\""))

# Core engine imports
from src.core.types import Article
from src.engine.unified_chain import unified_engine
from src.engine.enhanced_feeder import EnhancedNewsPipeline
from src.engine.source_registry import SourceRegistry
from src.engine.breaking_news_pipeline import BreakingNewsScanner
from src.engine.rejected_metadata_store import RejectedMetadataStore
from src.security.policy import (
    cors_headers,
    is_origin_allowed,
    is_public_path,
    rate_limit_headers,
    rate_limiter,
    verify_engine_api_key,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MainEngine")

# Silence noisy third-party loggers
for noisy in ("aiohttp.access", "aiohttp.server", "asyncio", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# =============================================================================
# ARTICLE RING BUFFER — Thread-safe in-memory store with timestamp index
# =============================================================================

class ArticleRingBuffer:
    """Fixed-capacity ring buffer with timestamp-based querying.

    Stores the last `capacity` articles pushed by the engine.
    Supports efficient ``since(timestamp)`` queries using a sorted deque.
    """

    def __init__(self, capacity: int = 5000):
        self._capacity = capacity
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=capacity)
        self._seen_ids: Set[str] = set()
        self._total_pushed: int = 0

    def push(self, article: Article) -> bool:
        """Push article into ring buffer.  Returns True if new, False if dup."""
        if article.id in self._seen_ids:
            return False

        article_dict = article.to_dict()
        article_dict["_engine_ts"] = datetime.now(UTC).isoformat()

        # Evict oldest if at capacity
        if len(self._buffer) >= self._capacity:
            evicted = self._buffer[0]
            self._seen_ids.discard(evicted.get("id", ""))

        self._buffer.append(article_dict)
        self._seen_ids.add(article.id)
        self._total_pushed += 1
        return True

    def since(self, timestamp: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Return articles pushed after `timestamp` (ISO 8601 string), newest first."""
        if not timestamp:
            # Return latest `limit` articles
            return list(reversed(list(self._buffer)))[:limit]

        try:
            cutoff = datetime.fromisoformat(timestamp)
        except (ValueError, TypeError):
            return list(reversed(list(self._buffer)))[:limit]

        results = []
        for art in reversed(self._buffer):
            engine_ts = art.get("_engine_ts")
            if engine_ts:
                try:
                    if datetime.fromisoformat(engine_ts) <= cutoff:
                        break
                except (ValueError, TypeError):
                    pass
            results.append(art)
            if len(results) >= limit:
                break

        return results

    def since_filtered(
        self,
        timestamp: Optional[str] = None,
        limit: int = 200,
        pipeline: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return articles filtered by pipeline type ('breaking', 'standard', or None for all)."""
        articles = self.since(timestamp=timestamp, limit=limit * 2)  # Fetch more to account for filtering
        if not pipeline:
            return articles[:limit]
        return [a for a in articles if a.get("pipeline") == pipeline][:limit]

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "buffered": len(self._buffer),
            "capacity": self._capacity,
            "total_pushed": self._total_pushed,
            "unique_ids": len(self._seen_ids),
        }


# =============================================================================
# SSE BROADCASTER — Push articles to connected SSE clients
# =============================================================================

class SSEBroadcaster:
    """Manages Server-Sent Events connections and broadcasts articles to all."""

    def __init__(self):
        self._clients: List[web.StreamResponse] = []

    def add_client(self, resp: web.StreamResponse) -> None:
        self._clients.append(resp)
        logger.info(f"SSE client connected ({len(self._clients)} total)")

    def remove_client(self, resp: web.StreamResponse) -> None:
        if resp in self._clients:
            self._clients.remove(resp)
            logger.info(f"SSE client disconnected ({len(self._clients)} remaining)")

    async def broadcast(self, article_dict: Dict[str, Any], event_type: str = "article") -> None:
        """Push article to all connected SSE clients.

        Args:
            article_dict: Article data to broadcast
            event_type: SSE event type - 'article' (standard) or 'breaking' (priority)
        """
        if not self._clients:
            return

        data = json.dumps(article_dict, default=str)
        message = f"event: {event_type}\ndata: {data}\n\n"

        disconnected = []
        for client in self._clients:
            try:
                await client.write(message.encode("utf-8"))
            except (ConnectionResetError, ConnectionAbortedError, Exception):
                disconnected.append(client)

        for client in disconnected:
            self.remove_client(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# =============================================================================
# MAIN ENGINE — Orchestrates everything
# =============================================================================

class MainEngine:
    """Central engine that runs the full pipeline and serves the HTTP/SSE API."""

    def __init__(
        self,
        port: int = 8080,
        host: str = "0.0.0.0",
        concurrency: int = 2,
        buffer_capacity: int = 5000,
        discovery_interval: int = 120,
    ):
        self.port = port
        self.host = host
        self.concurrency = concurrency
        self.discovery_interval = discovery_interval

        # Core components — use the global singleton that the pipeline also uses
        self.unified_engine = unified_engine
        self.pipeline: Optional[EnhancedNewsPipeline] = None
        self.ring_buffer = ArticleRingBuffer(capacity=buffer_capacity)
        self.sse = SSEBroadcaster()

        # 🔴 Breaking News Pipeline (Priority 1)
        self._rejected_store = RejectedMetadataStore()
        self._breaking_scanner: Optional[BreakingNewsScanner] = None

        # State
        self._running = False
        self._start_time: Optional[float] = None
        self._discovery_task: Optional[asyncio.Task] = None
        self._standard_publish_task: Optional[asyncio.Task] = None
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None

    # ── Article callback (invoked by FeedChain for every new article) ──

    def _on_article(self, article: Article) -> None:
        """Called by FeedChain subscriber for each new article that clears dedup + quality."""
        # Dynamically evaluate freshness if not already tagged
        if article.pipeline is None and self._breaking_scanner and article.published_at:
            freshness = self._breaking_scanner._freshness_gate.check(article)
            if freshness.is_any_fresh and self.unified_engine.quality.check_strict(article) == "pass":
                article.pipeline = "breaking"
            else:
                article.pipeline = "standard"
        elif article.pipeline is None:
            article.pipeline = "standard"

        is_new = self.ring_buffer.push(article)
        if is_new:
            pipeline_tag = article.pipeline or "standard"
            badge = "🔴⚡ BREAKING" if pipeline_tag == "breaking" else "🟢 Standard"
            logger.info(
                f"{badge} ← '{(article.title or 'Untitled')[:60]}' "
                f"[{article.source}] (buffer: {self.ring_buffer.stats['buffered']})"
            )
            # Schedule SSE broadcast (non-blocking from sync callback)
            try:
                loop = asyncio.get_running_loop()
                event_type = "breaking" if pipeline_tag == "breaking" else "article"
                loop.create_task(self.sse.broadcast(article.to_dict(), event_type=event_type))
            except RuntimeError:
                pass  # No event loop running yet

    # ── Pipeline lifecycle ──

    async def start_pipeline(self) -> None:
        """Initialize and start both breaking + standard pipelines."""
        logger.info("═" * 60)
        logger.info("  Tech News Scrapper — Main Engine Starting")
        logger.info("  🔴 Breaking News Pipeline (Priority 1) + 🟢 Standard Pipeline")
        logger.info("═" * 60)

        # 1. Subscribe to FeedChain BEFORE pipeline.start() so we capture
        #    every article that clears dedup + quality gates.
        self.unified_engine.initialize(concurrency=self.concurrency)
        self.unified_engine.subscribe(self._on_article)
        logger.info(f"✓ Unified Feed Chain initialized ({self.concurrency} workers)")

        # Log registered sources
        sources = self.unified_engine.registry.get_all_ordered()
        logger.info(f"✓ Source Registry loaded: {len(sources)} sources")
        for src in sources[:5]:
            logger.info(f"  • {src.name} ({src.type.value}) — tier {src.tier}")
        if len(sources) > 5:
            logger.info(f"  ... and {len(sources) - 5} more")

        # 2. 🔴 Start Breaking News Scanner (Priority 1)
        self._breaking_scanner = BreakingNewsScanner(
            dedup=self.unified_engine.dedup,
            quality=self.unified_engine.quality,
            feed=self.unified_engine.feed,
            rejected_store=self._rejected_store,
            hard_cutoff_minutes=30,
            soft_cutoff_minutes=60,
        )
        await self._breaking_scanner.start()
        logger.info("✓ 🔴 Breaking News Scanner started (Priority 1: ≤30min freshness)")

        # 3. Start the standard enhanced pipeline (adds API discovery + primp crawler)
        self.pipeline = EnhancedNewsPipeline(
            enable_discovery=True,
            max_articles=1000,
            max_age_hours=72,
        )
        await self.pipeline.start()
        logger.info("✓ 🟢 Standard News Pipeline started (72hr window, 20 articles/cycle)")

        # 4. Trigger initial fetch
        logger.info("🔍 Running initial unified discovery fetch...")
        articles = await self.pipeline.fetch_unified_live_feed(count=500)
        for article in articles:
            self.ring_buffer.push(article)
        logger.info(
            f"✓ Initial fetch complete: {len(articles)} articles loaded "
            f"(Buffer total: {self.ring_buffer.stats['buffered']})"
        )

        # 5. Start periodic standard discovery loop (with 2-min publish gaps)
        self._discovery_task = asyncio.create_task(self._standard_discovery_loop())
        logger.info(f"✓ Standard discovery loop active (every {self.discovery_interval}s)")

        # 6. Start the standard pipeline rate-limited publisher
        self._standard_publish_task = asyncio.create_task(self._standard_publish_loop())
        logger.info("✓ Standard rate-limited publisher active (2-min gaps, 20 articles/batch)")

        self._start_time = time.time()
        self._running = True

    async def _standard_discovery_loop(self) -> None:
        """Periodic background task for standard pipeline API discovery + RSS refresh."""
        while self._running:
            try:
                await asyncio.sleep(self.discovery_interval)
                if not self._running:
                    break

                # If breaking pipeline has fresh content, reduce standard pipeline priority
                if self._breaking_scanner and self._breaking_scanner.has_breaking_content:
                    logger.info(
                        "📡 Standard discovery: paused (breaking pipeline active)"
                    )
                    continue

                logger.info("📡 Executing standard discovery pass...")
                if self.pipeline:
                    articles = await self.pipeline.fetch_unified_live_feed(count=500)
                    logger.info(f"📡 Standard discovery pass complete: {len(articles)} articles")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Standard discovery loop error: {exc}")
                await asyncio.sleep(10)

    async def _standard_publish_loop(self) -> None:
        """
        Rate-limited publisher for standard pipeline articles.

        Publishes up to 20 articles per cycle with 2-minute gaps between each.
        Only active when breaking pipeline has no content.
        """
        while self._running:
            try:
                # Wait for breaking pipeline to be idle
                if self._breaking_scanner and self._breaking_scanner.has_breaking_content:
                    await asyncio.sleep(30)  # Check again in 30s
                    continue

                # Fetch standard pipeline articles
                if self.pipeline:
                    articles = await self.pipeline.fetch_unified_live_feed(count=20)
                    standard_articles = [
                        a for a in articles
                        if (a.pipeline or "standard") == "standard"
                    ]

                    if standard_articles:
                        logger.info(
                            f"🟢 Standard publisher: delivering {len(standard_articles)} "
                            f"articles with 2-min gaps"
                        )

                    for article in standard_articles[:20]:
                        if not self._running:
                            break

                        is_new = self.ring_buffer.push(article)
                        if is_new:
                            logger.info(
                                f"🟢 Standard → '{(article.title or 'Untitled')[:60]}'"
                            )

                        # 2-minute gap between each standard article
                        await asyncio.sleep(120)

                # Sleep before next batch if no articles
                await asyncio.sleep(self.discovery_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Standard publish loop error: {exc}")
                await asyncio.sleep(10)

    async def stop_pipeline(self) -> None:
        """Gracefully stop everything."""
        if not self._running:
            return
        logger.info("🛑 Shutting down Main Engine...")
        self._running = False

        # Stop breaking scanner first
        if self._breaking_scanner:
            self._breaking_scanner.stop()

        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass

        if self._standard_publish_task:
            self._standard_publish_task.cancel()
            try:
                await self._standard_publish_task
            except asyncio.CancelledError:
                pass

        self.unified_engine.unsubscribe(self._on_article)
        self.unified_engine.stop()

        if self.pipeline:
            await self.pipeline.stop()

        # Always explicitly stop background scheduler workers
        self.unified_engine.stop()
        logger.info("👋 Main Engine stopped cleanly.")

    # ── HTTP API Routes ──

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /api/v1/health — Engine health and statistics."""
        uptime = time.time() - self._start_time if self._start_time else 0
        sources = self.unified_engine.registry.get_all_ordered()

        data = {
            "status": "running" if self._running else "stopped",
            "uptime_seconds": round(uptime, 1),
            "buffer": self.ring_buffer.stats,
            "sse_clients": self.sse.client_count,
            "sources_registered": len(sources),
            "pipeline_stats": self.pipeline.get_stats() if self.pipeline else {},
            "breaking_stats": self._breaking_scanner.get_stats() if self._breaking_scanner else {},
            "rejected_store_stats": self._rejected_store.get_stats(),
        }
        return web.json_response(data)

    async def handle_feed(self, request: web.Request) -> web.Response:
        """GET /api/v1/feed?since=<iso>&limit=100&pipeline=breaking — Batch poll for articles."""
        since = request.query.get("since", None)
        pipeline_filter = request.query.get("pipeline", None)  # 'breaking', 'standard', or None
        try:
            limit = int(request.query.get("limit", "100"))
        except ValueError:
            limit = 100
        limit = min(limit, 500)

        articles = self.ring_buffer.since_filtered(
            timestamp=since, limit=limit, pipeline=pipeline_filter
        )

        return web.json_response({
            "count": len(articles),
            "articles": articles,
            "pipeline_filter": pipeline_filter,
            "server_time": datetime.now(UTC).isoformat(),
        })

    async def handle_sources(self, request: web.Request) -> web.Response:
        """GET /api/v1/sources — List all registered sources."""
        sources = self.unified_engine.registry.get_all_ordered()
        return web.json_response({
            "count": len(sources),
            "sources": [s.to_dict() for s in sources],
        })

    async def handle_stream(self, request: web.Request) -> web.StreamResponse:
        """GET /api/v1/stream — Server-Sent Events stream of real-time articles."""
        sse_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        # Apply CORS from shared policy
        origin = request.headers.get("Origin")
        sse_headers.update(cors_headers(origin))

        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers=sse_headers,
        )
        await resp.prepare(request)

        # Send initial heartbeat
        await resp.write(b"event: connected\ndata: {\"status\": \"connected\"}\n\n")

        self.sse.add_client(resp)

        try:
            # Keep connection alive with heartbeats
            while self._running:
                await asyncio.sleep(30)
                try:
                    await resp.write(b": heartbeat\n\n")
                except (ConnectionResetError, ConnectionAbortedError):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            self.sse.remove_client(resp)

        return resp

    # ── Web Server ──

    async def start_server(self) -> None:
        """Start the aiohttp web server."""
        self._app = web.Application()
        self._app.router.add_get("/api/v1/health", self.handle_health)
        self._app.router.add_get("/api/v1/feed", self.handle_feed)
        self._app.router.add_get("/api/v1/sources", self.handle_sources)
        self._app.router.add_get("/api/v1/stream", self.handle_stream)

        # Auth + CORS middleware using shared SecurityPolicy
        @web.middleware
        async def security_middleware(request, handler):
            origin = request.headers.get("Origin")

            # CORS preflight
            if request.method == "OPTIONS":
                resp = web.Response()
                resp.headers.update(cors_headers(origin))
                return resp

            # Authentication: skip for public paths
            if not is_public_path(request.path):
                api_key = request.headers.get("X-API-Key")
                if not verify_engine_api_key(api_key):
                    return web.json_response(
                        {"error": "API key required. Provide X-API-Key header."},
                        status=401,
                    )
                # Rate limiting
                key_id = api_key or "anonymous"
                if not rate_limiter.check_limit(key_id, "free"):
                    resp = web.json_response(
                        {"error": "Rate limit exceeded."},
                        status=429,
                    )
                    resp.headers.update(rate_limit_headers(key_id, "free", is_limited=True))
                    return resp

            resp = await handler(request)

            # CORS headers on every response
            resp.headers.update(cors_headers(origin))

            # Rate-limit headers on authenticated responses
            if not is_public_path(request.path):
                api_key = request.headers.get("X-API-Key")
                if api_key:
                    resp.headers.update(rate_limit_headers(api_key, "free"))

            return resp

        self._app.middlewares.append(security_middleware)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        logger.info(f"🌐 API Server running on http://{self.host}:{self.port}")
        logger.info(f"   GET /api/v1/health   — Health check")
        logger.info(f"   GET /api/v1/feed     — Batch article fetch")
        logger.info(f"   GET /api/v1/sources  — Registered sources")
        logger.info(f"   GET /api/v1/stream   — Real-time SSE stream")

    async def stop_server(self) -> None:
        """Stop the web server."""
        if self._runner:
            await self._runner.cleanup()

    # ── Full lifecycle ──

    async def run(self) -> None:
        """Start everything and block until shutdown signal."""
        await self.start_pipeline()
        await self.start_server()

        # Wait for shutdown signal
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _signal_handler():
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass  # Windows

        logger.info("═" * 60)
        logger.info("  Engine is LIVE — Press Ctrl+C to stop")
        logger.info("═" * 60)

        try:
            await stop_event.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop_pipeline()
            await self.stop_server()


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Tech News Scrapper — Main Engine Server"
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("ENGINE_PORT", "8080")),
        help="HTTP API port (default: 8080)",
    )
    parser.add_argument(
        "--host", type=str, default=os.getenv("ENGINE_HOST", "0.0.0.0"),
        help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=2,
        help="CyclicSourceScheduler worker count (default: 2)",
    )
    parser.add_argument(
        "--buffer-size", type=int, default=5000,
        help="Article ring buffer capacity (default: 5000)",
    )
    parser.add_argument(
        "--discovery-interval", type=int, default=120,
        help="Seconds between API discovery passes (default: 120)",
    )
    args = parser.parse_args()

    warnings.warn(
        "main_engine.py is deprecated and will be removed in Phase 9. "
        "Use 'python -m src.worker' for the ingestion worker or 'uvicorn src.api.app:app' for the API.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "⚠️ [DEPRECATION] main_engine.py is deprecated. Use 'python -m src.worker' for the canonical worker or 'uvicorn src.api.app:app' for the API."
    )

    engine = MainEngine(
        port=args.port,
        host=args.host,
        concurrency=args.concurrency,
        buffer_capacity=args.buffer_size,
        discovery_interval=args.discovery_interval,
    )
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
