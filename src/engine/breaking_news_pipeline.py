"""
BreakingNewsScanner — Priority 1 Pipeline for Ultra-Fresh News Delivery.

A dedicated, high-frequency scanner that runs independently of the standard
pipeline. Scans ALL sources every 30 seconds and applies strict freshness
and quality gates to identify genuinely breaking news.

Architecture:
    All Sources (RSS + API + Primp)
        → BreakingNewsScanner (30s loop)
        → FreshnessGate (HARD: ≤30 min, SOFT: ≤60 min)
        → QualityGate.check_strict() (title ≥15 chars, tech relevance)
        → DedupGate (prevent re-push)
        → FeedChain.push() with pipeline='breaking'
        → SSE broadcast with event type 'breaking'

When no breaking news is found for a full cycle, signals the standard
pipeline to activate its fallback delivery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, UTC
from typing import Any, Callable, Dict, List, Optional

from ..core.types import Article
from .freshness_gate import FreshnessGate
from .quality_gate import QualityGate
from .dedup_gate import DedupGate
from .feed_chain import FeedChain
from .rejected_metadata_store import RejectedMetadataStore
from .unified_chain import unified_engine

logger = logging.getLogger(__name__)


class BreakingNewsScanner:
    """
    High-frequency scanner for breaking news detection.

    Runs a tight 30-second loop scanning all sources for articles
    published within the last 30 minutes (hard) or 60 minutes (soft).

    When breaking news is found, it is pushed immediately to the FeedChain
    with pipeline='breaking' tag and SSE event type 'breaking'.

    When no breaking news is found for a complete scan cycle, sets
    `has_breaking_content = False` to signal the standard pipeline
    to begin its fallback delivery.
    """

    SCAN_INTERVAL_SECONDS = 30  # How often to scan all sources
    PIPELINE_TAG = "breaking"

    def __init__(
        self,
        dedup: DedupGate,
        quality: QualityGate,
        feed: FeedChain,
        rejected_store: Optional[RejectedMetadataStore] = None,
        hard_cutoff_minutes: int = 30,
        soft_cutoff_minutes: int = 60,
    ):
        """
        Initialize the breaking news scanner.

        Args:
            dedup: Shared DedupGate instance (same as standard pipeline)
            quality: Shared QualityGate instance
            feed: Shared FeedChain instance for pushing articles
            rejected_store: Optional store for rejected article metadata
            hard_cutoff_minutes: Primary freshness cutoff (default 30 min)
            soft_cutoff_minutes: Soft window cutoff (default 60 min)
        """
        self._dedup = dedup
        self._quality = quality
        self._feed = feed
        self._rejected_store = rejected_store or RejectedMetadataStore()
        self._freshness_gate = FreshnessGate(
            hard_cutoff_minutes=hard_cutoff_minutes,
            soft_cutoff_minutes=soft_cutoff_minutes,
        )

        # State
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        self._has_breaking_content = False  # Flag for standard pipeline
        self._last_breaking_time: Optional[datetime] = None

        # Callbacks for breaking news events
        self._breaking_callbacks: List[Callable[[Article], None]] = []

        # Statistics
        self._stats = {
            "scan_count": 0,
            "articles_scanned": 0,
            "articles_passed_freshness": 0,
            "articles_passed_quality": 0,
            "articles_pushed": 0,
            "articles_rejected_stale": 0,
            "articles_rejected_quality": 0,
            "articles_rejected_dedup": 0,
            "last_scan_ms": 0,
            "last_scan_time": None,
            "consecutive_empty_scans": 0,
        }

    @property
    def has_breaking_content(self) -> bool:
        """Whether the last scan found any breaking news."""
        return self._has_breaking_content

    @property
    def last_breaking_time(self) -> Optional[datetime]:
        """When breaking news was last found."""
        return self._last_breaking_time

    def subscribe_breaking(self, callback: Callable[[Article], None]) -> None:
        """Register a callback for breaking news articles (in addition to FeedChain)."""
        if callback not in self._breaking_callbacks:
            self._breaking_callbacks.append(callback)

    def unsubscribe_breaking(self, callback: Callable[[Article], None]) -> None:
        """Remove a breaking news callback."""
        if callback in self._breaking_callbacks:
            self._breaking_callbacks.remove(callback)

    async def start(self) -> None:
        """Start the breaking news scan loop."""
        if self._running:
            return

        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(
            f"🔴 BreakingNewsScanner started "
            f"(interval={self.SCAN_INTERVAL_SECONDS}s, "
            f"hard_cutoff={self._freshness_gate.hard_cutoff_minutes}min, "
            f"soft_cutoff={self._freshness_gate.soft_cutoff_minutes}min)"
        )

    def stop(self) -> None:
        """Stop the breaking news scan loop."""
        self._running = False
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        logger.info("🔴 BreakingNewsScanner stopped")

    async def _scan_loop(self) -> None:
        """Main scan loop — runs every SCAN_INTERVAL_SECONDS."""
        while self._running:
            try:
                t_start = time.perf_counter()

                breaking_count = await self._execute_scan()

                elapsed_ms = (time.perf_counter() - t_start) * 1000
                self._stats["last_scan_ms"] = round(elapsed_ms, 1)
                self._stats["last_scan_time"] = datetime.now(UTC).isoformat()
                self._stats["scan_count"] += 1

                if breaking_count > 0:
                    self._has_breaking_content = True
                    self._last_breaking_time = datetime.now(UTC)
                    self._stats["consecutive_empty_scans"] = 0
                    logger.info(
                        f"🔴 BREAKING: {breaking_count} fresh article(s) pushed "
                        f"[scan #{self._stats['scan_count']}, {elapsed_ms:.0f}ms]"
                    )
                else:
                    self._stats["consecutive_empty_scans"] += 1
                    # After 2 consecutive empty scans (60s), signal standard pipeline
                    if self._stats["consecutive_empty_scans"] >= 2:
                        self._has_breaking_content = False

                await asyncio.sleep(self.SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"BreakingNewsScanner loop error: {e}")
                await asyncio.sleep(5)

    async def _execute_scan(self) -> int:
        """
        Execute a single breaking news scan.

        Drains the FeedChain for recently pushed articles from the
        CyclicSourceScheduler and checks them against freshness + quality gates.

        Returns:
            Number of breaking articles pushed
        """
        # Get all recently processed articles from the unified engine
        # The CyclicSourceScheduler continuously feeds articles into the FeedChain
        # We scan what's available without draining (peek approach via direct source fetch)
        breaking_pushed = 0

        # Trigger a fast source refresh to get latest articles
        await unified_engine.start()

        # Get articles that have been processed by the cyclic scheduler
        # We use drain to get them, then re-push the non-breaking ones
        all_articles = unified_engine.get_articles(count=500)
        self._stats["articles_scanned"] += len(all_articles)

        non_breaking_articles: List[Article] = []

        for article in all_articles:
            # 1. Freshness Gate — the core differentiator
            freshness = self._freshness_gate.check(article)

            if not freshness.is_any_fresh:
                # Not fresh enough for breaking → route to standard pipeline
                self._stats["articles_rejected_stale"] += 1
                non_breaking_articles.append(article)
                if freshness.rejection_reason:
                    self._rejected_store.store(
                        article, freshness.rejection_reason, "breaking"
                    )
                continue

            self._stats["articles_passed_freshness"] += 1

            # 2. Strict Quality Gate — harder checks for breaking
            quality_result = self._quality.check_strict(article)
            if quality_result != "pass":
                self._stats["articles_rejected_quality"] += 1
                non_breaking_articles.append(article)  # May still qualify for standard
                self._rejected_store.store(article, quality_result, "breaking")
                continue

            self._stats["articles_passed_quality"] += 1

            # 3. Dedup Gate — prevent re-pushing same breaking article
            if self._dedup.check_and_add(article):
                self._stats["articles_rejected_dedup"] += 1
                continue

            # ✅ BREAKING — Tag and push immediately
            article.pipeline = self.PIPELINE_TAG

            await self._feed.push(article)
            breaking_pushed += 1
            self._stats["articles_pushed"] += 1

            # Fire breaking callbacks
            for cb in self._breaking_callbacks:
                try:
                    cb(article)
                except Exception as e:
                    logger.error(f"Breaking callback error: {e}")

            logger.info(
                f"🔴⚡ BREAKING [{freshness.age_minutes:.0f}min]: "
                f"'{(article.title or '')[:70]}' [{article.source}]"
            )

        # Re-push non-breaking articles back to FeedChain for standard pipeline
        for article in non_breaking_articles:
            article.pipeline = "standard"
            try:
                await self._feed.push(article)
            except Exception:
                pass  # Queue full is OK, standard pipeline will refetch

        return breaking_pushed

    def get_stats(self) -> Dict[str, Any]:
        """Get breaking news scanner statistics."""
        return {
            **self._stats,
            "running": self._running,
            "has_breaking_content": self._has_breaking_content,
            "last_breaking_time": (
                self._last_breaking_time.isoformat()
                if self._last_breaking_time
                else None
            ),
            "freshness_config": {
                "hard_cutoff_minutes": self._freshness_gate.hard_cutoff_minutes,
                "soft_cutoff_minutes": self._freshness_gate.soft_cutoff_minutes,
            },
            "rejected_store_stats": self._rejected_store.get_stats(),
        }
