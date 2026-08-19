"""
Canonical Production Ingestion Worker Entrypoint.
Location: src/worker.py

Runs the authoritative UnifiedFeedChainEngine orchestrating:
SourceRegistry -> ZombieSwarm -> StarvationSafeQueue -> CanonicalPipelineRunner (S01-S11) -> SQLite Storage

Usage:
    python -m src.worker
    python -m src.worker --concurrency 4 --db-path /data/technews.db
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import signal
import sys
from typing import Optional

from src.engine.unified_chain import UnifiedFeedChainEngine
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository
from src.storage.sqlite_source_health_repository import SqliteSourceHealthRepository

logger = logging.getLogger("technews.worker")

DEFAULT_DB_PATH = Path("data/technews_canonical.db")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tech News Scrapper — Canonical Ingestion Worker"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("TECHNEWS_WORKER_CONCURRENCY", "2")),
        help="Worker concurrency multiplier (default: 2)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=os.getenv("TECHNEWS_DB_PATH")
        or os.getenv("TECHNEWS_CANONICAL_DB_PATH")
        or str(DEFAULT_DB_PATH),
        help="Path to SQLite canonical database",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.getenv("TECHNEWS_LOG_LEVEL", "INFO").upper(),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("TECHNEWS_WORKER_TIMEOUT", "0")),
        help="Optional automatic shutdown timeout in seconds (0 = run indefinitely)",
    )
    return parser.parse_args()


async def run_worker(
    db_path: Path,
    concurrency: int = 2,
    timeout: float = 0.0,
    shutdown_event: Optional[asyncio.Event] = None,
) -> None:
    """Run the canonical UnifiedFeedChainEngine worker lifecycle."""
    logger.info(
        f"🚀 Initializing Tech News Scrapper Ingestion Worker (DB: {db_path}, Concurrency: {concurrency}, Timeout: {timeout}s)..."
    )

    # 1. Initialize SQLite storage and schema
    db_engine = SqliteEngine(db_path)
    await db_engine.initialize_schema()

    # 2. Instantiate persistent repositories
    article_repo = SqliteArticleRepository(engine=db_engine)
    event_repo = SqliteEventRepository(engine=db_engine, auto_init=True)
    health_repo = SqliteSourceHealthRepository(engine=db_engine)

    # 3. Instantiate and initialize the canonical UnifiedFeedChainEngine
    engine = UnifiedFeedChainEngine(
        event_repository=event_repo,
        article_repository=article_repo,
        health_repository=health_repo,
    )
    engine.initialize(concurrency=concurrency)

    # 4. Setup graceful termination event and signal handlers
    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _signal_handler(sig_name: str) -> None:
        logger.info(f"🛑 Received {sig_name} signal, initiating graceful worker shutdown...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig.name)
        except (NotImplementedError, RuntimeError):
            # Windows or non-main thread fallback
            pass

    # Optional timeout trigger for calibration or smoke runs
    timeout_task = None
    if timeout > 0:
        async def _timeout_trigger():
            await asyncio.sleep(timeout)
            logger.info(f"⏱️ Worker timeout limit of {timeout}s reached, stopping worker gracefully...")
            shutdown_event.set()
        timeout_task = asyncio.create_task(_timeout_trigger())

    # 5. Start the background zombie swarm loop
    logger.info("🧟 Starting Zombie Swarm autonomous acquisition...")
    await engine.start(concurrency=concurrency)
    logger.info("🟢 Ingestion Worker running. Awaiting stop signal...")

    try:
        await shutdown_event.wait()
    finally:
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()
        # 6. Graceful cleanup and teardown
        logger.info("🧹 Draining pipeline, flushing health states, and terminating swarm...")
        await engine.aclose()
        await db_engine.aclose()
        logger.info("✅ Ingestion Worker stopped cleanly.")


def main() -> None:
    """Main CLI entrypoint."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(
            run_worker(
                db_path=db_path,
                concurrency=args.concurrency,
                timeout=args.timeout,
            )
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Worker interrupted by user.")
    except Exception as e:
        logger.critical(f"Fatal worker exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
