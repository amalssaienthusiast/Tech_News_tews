"""
FreshnessGate — Strict Time-Precision Module for Breaking News Pipeline.

Determines whether an article is fresh enough for the breaking news pipeline.
Uses a hard cutoff (default 30 minutes) and a soft window (30-60 minutes)
for de-prioritized but still qualifying articles.

This is a PRECISION INSTRUMENT — no fuzzy date acceptance, no undated articles.
If we can't prove freshness, the article is rejected.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Optional

from ..core.types import Article

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    """Result of a freshness check."""
    is_fresh: bool           # True if article passes the hard cutoff
    is_soft_fresh: bool      # True if article is within soft window (30-60 min)
    age_minutes: float       # Age in minutes (negative if in the future)
    confidence: float        # 1.0 = published_at used, 0.5 = scraped_at fallback
    rejection_reason: Optional[str] = None  # Why it failed, if it did

    @property
    def is_any_fresh(self) -> bool:
        """True if the article qualifies under either hard or soft cutoff."""
        return self.is_fresh or self.is_soft_fresh


class FreshnessGate:
    """
    Strict freshness gate for the breaking news pipeline.

    Hard cutoff: Articles must be ≤ hard_cutoff_minutes old (default 30).
    Soft window: Articles between hard and soft cutoff (30-60 min) qualify
                 but are de-prioritized.

    Articles with NO timestamp are ALWAYS rejected — the breaking pipeline
    requires provable freshness.
    """

    def __init__(
        self,
        hard_cutoff_minutes: int = 30,
        soft_cutoff_minutes: int = 60,
    ):
        self.hard_cutoff_minutes = hard_cutoff_minutes
        self.soft_cutoff_minutes = soft_cutoff_minutes

    def check(self, article: Article) -> FreshnessResult:
        """
        Check if article meets freshness requirements.

        Priority:
        1. Uses published_at if available (confidence=1.0)
        2. Falls back to scraped_at (confidence=0.5)
        3. No timestamp → REJECTED

        Returns:
            FreshnessResult with detailed freshness assessment
        """
        now = datetime.now(UTC)

        # Determine the best available timestamp
        timestamp = article.published_at
        confidence = 1.0

        if timestamp is None:
            timestamp = article.scraped_at if article.scraped_at else None
            confidence = 0.5

        if timestamp is None:
            return FreshnessResult(
                is_fresh=False,
                is_soft_fresh=False,
                age_minutes=-1.0,
                confidence=0.0,
                rejection_reason="no_timestamp",
            )

        # Ensure timezone awareness
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        # Calculate age
        age_delta = now - timestamp
        age_minutes = age_delta.total_seconds() / 60.0

        # Future articles (clock skew) — allow up to 5 minutes in the future
        if age_minutes < -5.0:
            return FreshnessResult(
                is_fresh=False,
                is_soft_fresh=False,
                age_minutes=age_minutes,
                confidence=confidence,
                rejection_reason="future_timestamp",
            )

        # Hard cutoff check
        is_hard_fresh = age_minutes <= self.hard_cutoff_minutes

        # Soft window check (between hard and soft cutoff)
        is_soft_fresh = (
            not is_hard_fresh
            and age_minutes <= self.soft_cutoff_minutes
        )

        # Build rejection reason if neither passes
        rejection_reason = None
        if not is_hard_fresh and not is_soft_fresh:
            rejection_reason = f"stale_{age_minutes:.0f}min"

        return FreshnessResult(
            is_fresh=is_hard_fresh,
            is_soft_fresh=is_soft_fresh,
            age_minutes=round(age_minutes, 1),
            confidence=confidence,
            rejection_reason=rejection_reason,
        )

    def check_batch(self, articles: list[Article]) -> list[tuple[Article, FreshnessResult]]:
        """Check freshness for a batch of articles, returning results paired with articles."""
        return [(article, self.check(article)) for article in articles]

    def filter_fresh(self, articles: list[Article], include_soft: bool = True) -> list[Article]:
        """
        Filter a list of articles to only those passing freshness checks.

        Args:
            articles: Articles to filter
            include_soft: If True, also include soft-window articles (30-60 min)

        Returns:
            Filtered list sorted by freshness (newest first)
        """
        fresh = []
        for article in articles:
            result = self.check(article)
            if result.is_fresh or (include_soft and result.is_soft_fresh):
                fresh.append((article, result))

        # Sort by age (newest first)
        fresh.sort(key=lambda pair: pair[1].age_minutes)

        return [article for article, _ in fresh]
