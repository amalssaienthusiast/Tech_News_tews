"""
Stage 2: Freshness Evaluator.
Location: src/pipeline/stages/s02_freshness.py

Evaluates temporal freshness against canonical FreshnessLevel boundaries:
- BREAKING:   [0, 5] minutes
- VERY_FRESH: (5, 30] minutes
- FRESH:      (30, 120] minutes
- RECENT:     (120, 360] minutes (2-6 hours)
- AGING:      (360, 1440] minutes (6-24 hours)
- OLD:        (1440, 4320] minutes (24-72 hours)
- STALE:      > 4320 minutes (>72 hours) -> Discard / Reject
- UNKNOWN:    Undated article fallback

Rejects STALE articles according to the approved Phase 3 policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import logging
import time
from typing import Optional

from ...domain.enums import FreshnessLevel
from ...domain.models import NormalizedArticle
from ...domain.validators import DomainValidationError
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    """Diagnostic outcome of freshness evaluation."""
    level: FreshnessLevel
    score: float           # 0.0 to 1.0 (continuous decay)
    age_minutes: Optional[float]
    evaluated_at: datetime


def calculate_freshness_score(age_minutes: Optional[float]) -> float:
    """
    Calculate continuous freshness score in [0.0, 1.0]:
    - UNKNOWN -> 0.50 (neutral fallback)
    - 0 to 5 min -> 1.00
    - 5 min to 72 hours -> linear decay down to 0.05
    - > 72 hours (4320 min) -> 0.00
    """
    if age_minutes is None:
        return 0.50
    if age_minutes <= 0:
        return 1.00
    if age_minutes <= 5.0:
        return 1.00
    if age_minutes >= 4320.0:
        return 0.00
    # Linear decay from 1.0 down to 0.05 over 72 hours (4320 minutes)
    decay = 1.0 - (age_minutes / 4320.0) * 0.95
    return round(max(0.0, min(1.0, decay)), 3)


class FreshnessEvaluator:
    """
    Stage 2: Implements PipelineStage[NormalizedArticle, NormalizedArticle].
    
    Evaluates temporal freshness and filters out STALE articles.
    """

    @property
    def name(self) -> str:
        return "freshness_evaluator"

    @property
    def stage_number(self) -> int:
        return 2

    async def process(
        self,
        input_item: NormalizedArticle,
        context: PipelineContext,
    ) -> Optional[NormalizedArticle]:
        """
        Evaluate freshness of the article.
        Returns the article with freshness metadata, or None if dropped as STALE.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, NormalizedArticle):
            raise DomainValidationError(f"FreshnessEvaluator expects NormalizedArticle, got {type(input_item)}")

        now_utc = datetime.now(UTC)
        published_at = input_item.published_at

        if published_at is None:
            level = FreshnessLevel.UNKNOWN
            age_minutes = None
        else:
            # Calculate age in minutes
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            
            delta = now_utc - published_at
            age_minutes = delta.total_seconds() / 60.0
            
            # Future timestamp protection (clamp to 0 / BREAKING)
            if age_minutes < 0:
                logger.debug(f"Article '{input_item.id}' has future timestamp ({published_at}). Clamping to 0m.")
                age_minutes = 0.0

            level = FreshnessLevel.from_age_minutes(age_minutes)

        score = calculate_freshness_score(age_minutes)
        result = FreshnessResult(
            level=level,
            score=score,
            age_minutes=round(age_minutes, 2) if age_minutes is not None else None,
            evaluated_at=now_utc,
        )

        context.set("freshness_result", result)

        # STALE Rejection Policy (>72h)
        if level == FreshnessLevel.STALE:
            context.abort(f"Article '{input_item.id}' rejected as STALE (age: {age_minutes:.1f}m > 4320m)")
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.record_metric(self.name, elapsed_ms)
            return None

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
