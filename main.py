"""
[DEPRECATED] Tech News Scraper — legacy entry point.

DEPRECATION NOTICE (Phase 8H Hardening):
This module runs the uncoordinated legacy aggregator and supervisor.
It is superseded by the canonical production runtime:
  - Canonical API:            uvicorn src.api.app:app --port 8000
  - Canonical Ingestion Worker: python -m src.worker
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import subprocess
import sys
import time
import warnings
from multiprocessing import Process

import hashlib
from datetime import UTC, datetime

from config.config import load_config
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle
from src.feed_generator.live_feed import LiveFeedGenerator
from src.scrapers.factory import ScraperFactory
from src.scheduler.task_scheduler import ScraperScheduler
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine

logger = logging.getLogger("aggregator")


class RealTimeNewsAggregator:
    """Main application class — runs the scraping/dedup/storage pipeline."""

    def __init__(self) -> None:
        self.config = load_config()
        self.scrapers: list = []
        self.scheduler: ScraperScheduler | None = None
        self.feed_generator = LiveFeedGenerator()
        self.engine = SqliteEngine()
        self.article_repo = SqliteArticleRepository(engine=self.engine)
        self.logger = logging.getLogger("aggregator")
        self._shutting_down = False

    async def initialize(self) -> None:
        """Initialize the aggregator."""
        self.logger.info("Initializing Real-Time News Aggregator")
        self.scrapers = await self._create_scrapers()
        await self.engine.initialize_schema()

        max_concurrent = self.config["general"]["max_concurrent_scrapers"]
        self.scheduler = ScraperScheduler(
            self.scrapers, max_concurrent, on_result=self._on_scraper_result
        )
        self.logger.info("Initialized %d scrapers", len(self.scrapers))

    async def _create_scrapers(self) -> list:
        """Create scraper instances from config."""
        scrapers = []
        factory = ScraperFactory()
        for source_config in self.config["sources"]:
            if source_config.get("enabled", True):
                scraper = factory.create_scraper(source_config)
                if scraper:
                    scrapers.append(scraper)
        return scrapers

    async def run_continuous(self) -> None:
        """Run aggregator continuously. Each source is scraped on its own
        configured refresh_rate by scheduler.start(); results arrive via
        _on_scraper_result as each source's cycle completes."""
        self.logger.info("Starting continuous aggregation")
        try:
            await self.scheduler.start()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Error in scheduler: %s", e)
        finally:
            await self.shutdown()

    async def _on_scraper_result(self, scraper_name: str, articles: list) -> None:
        """Callback invoked by the scheduler whenever a source finishes a scrape cycle."""
        try:
            feed = await self.feed_generator.generate_feed([articles])
            if feed.get("articles"):
                now = datetime.now(UTC)
                domain_articles = []
                for raw in feed["articles"]:
                    url = raw.get("url") or raw.get("link") or ""
                    if not url:
                        continue
                    aid = hashlib.sha256(url.encode()).hexdigest()[:16]
                    domain_articles.append(
                        NormalizedArticle(
                            id=aid,
                            canonical_url=url,
                            original_url=url,
                            title=raw.get("title") or "Untitled",
                            clean_text=raw.get("content") or raw.get("summary") or "",
                            summary=raw.get("summary"),
                            source_id=raw.get("source") or "scraper",
                            source_name=raw.get("source") or "Scraper",
                            source_tier=SourceTier.TIER_3_COMMUNITY,
                            zombie_species=ZombieSpecies.RAW_HTTP,
                            discovered_at=now,
                            published_at=raw.get("published_at") if isinstance(raw.get("published_at"), datetime) else now,
                            language="en",
                            image_url=raw.get("image_url"),
                            authors=tuple(raw.get("authors") or ()),
                            tags=tuple(raw.get("tags") or ()),
                            metadata={},
                        )
                    )
                if domain_articles:
                    await self.article_repo.save_articles(domain_articles)
                self.logger.info(
                    "Statistics - Source: %s, Scraped: %d, Unique after dedup: %d",
                    scraper_name, len(articles), len(feed["articles"]),
                )
        except Exception as e:
            self.logger.error("Failed to process results from %s: %s", scraper_name, e)

    async def shutdown(self) -> None:
        """Shutdown gracefully. Safe to call more than once."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.logger.info("Shutting down...")
        if self.scheduler:
            self.scheduler.stop()
        for scraper in self.scrapers:
            try:
                await scraper.close()
            except Exception as e:
                self.logger.warning("Error closing scraper %s: %s", scraper, e)
        await self.engine.aclose()
        self.logger.info("Shutdown complete")


# ─────────────────────────────────────────────────────────────────────────────
# Supervised API process
# ─────────────────────────────────────────────────────────────────────────────
class SupervisedAPIProcess:
    """Runs the FastAPI app in a child process with crash detection and restart.

    The child process runs `uvicorn src.api.app:app`. We use a child Process
    rather than importing uvicorn into the parent so that:
      - A crash in the API cannot take down the aggregator event loop.
      - The API can be restarted independently.
      - SIGTERM to the parent is forwarded to the child for graceful drain.

    For production multi-worker deployments, prefer:
        gunicorn src.api.app:app -w 4 -k uvicorn.workers.UvicornWorker
    This class is the development fallback.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        max_restart_attempts: int = 3,
        restart_cooldown: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.max_restart_attempts = max_restart_attempts
        self.restart_cooldown = restart_cooldown
        self._process: Process | None = None
        self._restart_attempts = 0
        self._should_run = False

    @staticmethod
    def _run_uvicorn(host: str, port: int) -> None:
        """Target function for the child process."""
        import uvicorn
        uvicorn.run(
            "src.api.app:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
            access_log=False,
        )

    def start(self) -> None:
        """Start the API child process."""
        self._should_run = True
        self._restart_attempts = 0
        self._spawn()

    def _spawn(self) -> None:
        self._process = Process(
            target=self._run_uvicorn,
            args=(self.host, self.port),
            daemon=False,
        )
        self._process.start()
        logger.info(
            "API process started (pid=%d) on %s:%d",
            self._process.pid, self.host, self.port,
        )

    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def check_and_restart(self) -> bool:
        """Check if the API process is alive; restart if it has crashed.

        Returns True if the API is currently running (either because it
        never crashed, or because it was successfully restarted).
        Returns False if max_restart_attempts has been exceeded.
        """
        if not self._should_run:
            return False
        if self.is_alive():
            return True

        # Process has crashed
        exitcode = self._process.exitcode if self._process else "unknown"
        self._restart_attempts += 1
        if self._restart_attempts > self.max_restart_attempts:
            logger.error(
                "API process crashed (exit=%s); max restart attempts (%d) exceeded — giving up",
                exitcode, self.max_restart_attempts,
            )
            return False

        logger.warning(
            "API process crashed (exit=%s); restarting (attempt %d/%d) in %.1fs",
            exitcode, self._restart_attempts, self.max_restart_attempts, self.restart_cooldown,
        )
        time.sleep(self.restart_cooldown)
        self._spawn()
        return True

    def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop the API process. SIGTERM → wait → SIGKILL."""
        self._should_run = False
        if self._process is None or not self._process.is_alive():
            return

        logger.info("Stopping API process (pid=%d), grace period %.1fs",
                    self._process.pid, timeout)
        # Send SIGTERM to the child for graceful drain
        if self._process.pid:
            try:
                os.kill(self._process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return

        # Wait up to `timeout` seconds for graceful exit
        join_start = time.time()
        self._process.join(timeout=timeout)
        if self._process.is_alive():
            logger.warning(
                "API process did not exit after %.1fs — sending SIGKILL", timeout
            )
            self._process.kill()
            self._process.join(timeout=5.0)
        logger.info("API process stopped")


# Need os import for kill()
import os


async def run_with_supervised_api(aggregator: RealTimeNewsAggregator, host: str, port: int) -> None:
    """Run the aggregator and a supervised API process concurrently.

    The aggregator runs in the main event loop. The API runs in a child
    process. A background task checks is_alive() every 5s and restarts
    the API if it crashes.
    """
    api = SupervisedAPIProcess(host=host, port=port)
    api.start()

    async def _watchdog():
        while True:
            await asyncio.sleep(5.0)
            if not api.check_and_restart():
                logger.error("API watchdog: failed to maintain API process — continuing aggregator-only")
                return

    watchdog_task = asyncio.create_task(_watchdog())

    loop = asyncio.get_running_loop()

    def handle_signal():
        logger.info("Signal received — initiating shutdown")
        asyncio.create_task(aggregator.shutdown())
        # Stop the API in a thread to avoid blocking the loop
        import threading
        threading.Thread(target=api.stop, kwargs={"timeout": 30.0}, daemon=True).start()
        watchdog_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda *_: handle_signal())

    try:
        await aggregator.initialize()
        await aggregator.run_continuous()
    except Exception as e:
        logger.error("Fatal error: %s", e)
        await aggregator.shutdown()
    finally:
        api.stop(timeout=30.0)
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass


def setup_logging(level: str = "INFO") -> None:
    """Configure logging.

    P0-F: now wires the structured logging from src.monitoring.logging_configuration
    (previously orphan — see audit §8.1). In production, set LOG_FORMAT=json
    to emit structured JSON logs suitable for log aggregation (ELK, Loki, etc.).
    Falls back to plain text for development.
    """
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    json_mode = log_format == "json"
    log_level = getattr(logging, level.upper(), logging.INFO)
    log_file = os.getenv("LOG_FILE")  # optional; if set, logs also go to this file

    try:
        from src.monitoring.logging_configuration import configure_logging
        configure_logging(
            json_format=json_mode,
            level=log_level,
            log_file=log_file,
        )
    except Exception as e:
        # Fallback to basicConfig if the structured logging module fails to import
        # (e.g., in test environments where the module is not available)
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.StreamHandler(sys.stderr)],
        )
        logging.getLogger(__name__).warning(
            "Structured logging unavailable (%s); falling back to basicConfig", e
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="technews",
        description="Tech News Scraper — real-time news aggregation + optional API.",
    )
    api_group = p.add_mutually_exclusive_group()
    api_group.add_argument(
        "--with-api", action="store_true",
        help="Start the FastAPI API in a supervised child process (development mode).",
    )
    api_group.add_argument(
        "--no-api", action="store_true",
        help="Explicitly skip the API (default behaviour; for backwards compatibility).",
    )
    p.add_argument("--host", default="0.0.0.0", help="API bind host (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="API bind port (default: 8000)")
    p.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    warnings.warn(
        "main.py is deprecated and will be removed in Phase 9. "
        "Use 'python -m src.worker' for the ingestion worker or 'uvicorn src.api.app:app' for the API.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "⚠️ [DEPRECATION] main.py is deprecated. Use 'python -m src.worker' for the canonical worker or 'uvicorn src.api.app:app' for the API."
    )

    aggregator = RealTimeNewsAggregator()

    if args.with_api:
        logger.info("Starting in aggregator+API mode (supervised)")
        await run_with_supervised_api(aggregator, args.host, args.port)
    else:
        # Aggregator-only mode (default; backwards-compatible)
        if not args.no_api:
            logger.info("Starting in aggregator-only mode (use --with-api to also start the API)")
        loop = asyncio.get_running_loop()

        def handle_signal():
            logger.info("Signal received — initiating shutdown")
            asyncio.create_task(aggregator.shutdown())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                signal.signal(sig, lambda *_: handle_signal())

        try:
            await aggregator.initialize()
            await aggregator.run_continuous()
        except Exception as e:
            logger.error("Fatal error: %s", e)
            await aggregator.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
