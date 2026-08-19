"""
Stage 8: Scoring Engine.
Location: src/pipeline/stages/s08_scoring.py

Computes multi-dimensional intelligence scores for canonical TechEvent aggregates:
- Confidence: Source tier hierarchy + multi-source distinct corroboration
- Importance: Real-world significance and high-impact technology domain signals
- Novelty: Evolutionary stage of event lifecycle (initial discovery vs follow-up updates)
- Freshness: Categorical FreshnessLevel + continuous decay score [0.0, 1.0]
- Breaking: Derived invariant: (freshness == BREAKING and confidence >= 0.70 and importance >= 0.60)

Guarantees:
- Pure stage isolation: zero clustering mutation, zero enrichment, persistence, or publication.
- Deterministic score computation with named constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import logging
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from ...domain.enums import FreshnessLevel, SourceTier
from ...domain.models import TechEvent, EventSourceEvidence
from ...domain.validators import DomainValidationError, validate_score_range
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)

# =============================================================================
# SCORING WEIGHTS & NAMED CONSTANTS
# =============================================================================

# 1. Base Confidence by Highest Source Tier
TIER_BASE_CONFIDENCE: Dict[SourceTier, float] = {
    SourceTier.TIER_1_PREMIUM: 0.70,
    SourceTier.TIER_2_SPECIALIST: 0.50,
    SourceTier.TIER_3_COMMUNITY: 0.30,
    SourceTier.TIER_4_DISCOVERY: 0.15,
}
PRIMARY_SOURCE_BONUS = 0.05
DISTINCT_TIER1_2_CORROBORATION_BONUS = 0.15
DISTINCT_TIER3_CORROBORATION_BONUS = 0.05
MAX_CORROBORATION_BONUS = 0.30

# 2. Importance Signals
BASE_IMPORTANCE = 0.50

HIGH_IMPACT_PATTERNS: Tuple[Tuple[re.Pattern, float], ...] = (
    # Critical Security / Zero-Days / Exploits (+0.25)
    (re.compile(r"\b(zero-day|0-day|critical vulnerability|ransomware|cve-\d{4}-\d+|remote code execution|active exploit)\b", re.IGNORECASE), 0.25),
    # Frontier AI / Breakthrough Architecture (+0.20)
    (re.compile(r"\b(gpt-5|gpt-4|claude 3\.5|gemini 1\.5|frontier model|quantum supremacy|breakthrough|unveils new architecture)\b", re.IGNORECASE), 0.20),
    # Major Acquisitions / Regulatory / Antitrust (+0.20)
    (re.compile(r"\b(antitrust|acquisition|acquires|billion|sec charges|ftc|lawsuit|merger)\b", re.IGNORECASE), 0.20),
    # Core Infrastructure / Standard Milestones (+0.15)
    (re.compile(r"\b(linux kernel|webassembly|compiler|major outage|data breach|cyberattack)\b", re.IGNORECASE), 0.15),
)

LOW_IMPACT_PATTERNS: Tuple[Tuple[re.Pattern, float], ...] = (
    # Minor Tutorials, Opinions, Routine Updates (-0.20)
    (re.compile(r"\b(how to|tutorial|getting started with|my thoughts on|opinion|tips and tricks|minor bug fix)\b", re.IGNORECASE), -0.20),
)

# 3. Novelty Decay Parameters
BASE_NOVELTY = 1.0
TIMELINE_DECAY_STEP = 0.15
SOURCE_DECAY_STEP = 0.05
MIN_NOVELTY = 0.20


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================

def compute_confidence(sources: List[EventSourceEvidence]) -> float:
    """
    Compute factual confidence score based on source tier hierarchy and
    multi-source distinct corroboration.
    
    Prevents single-source inflation and ensures multiple distinct sources
    are required to reach maximum confidence.
    """
    if not sources:
        return 0.0

    # 1. Determine highest quality tier present
    highest_tier = min(s.source_tier for s in sources)
    base = TIER_BASE_CONFIDENCE.get(highest_tier, 0.20)

    # Primary source bonus
    if any(s.is_primary for s in sources):
        base += PRIMARY_SOURCE_BONUS

    # 2. Corroboration bonus: count distinct source names (not duplicate articles from same publisher)
    seen_source_names: Set[str] = set()
    corroboration_bonus = 0.0

    for s in sources:
        s_name_lower = s.source_name.lower().strip()
        if s_name_lower in seen_source_names:
            continue
        seen_source_names.add(s_name_lower)

        # Award corroboration bonus for secondary distinct sources
        if len(seen_source_names) > 1:
            if s.source_tier in (SourceTier.TIER_1_PREMIUM, SourceTier.TIER_2_SPECIALIST):
                corroboration_bonus += DISTINCT_TIER1_2_CORROBORATION_BONUS
            elif s.source_tier == SourceTier.TIER_3_COMMUNITY:
                corroboration_bonus += DISTINCT_TIER3_CORROBORATION_BONUS

    corroboration_bonus = min(MAX_CORROBORATION_BONUS, corroboration_bonus)
    final_confidence = min(1.0, base + corroboration_bonus)
    return round(final_confidence, 3)


def compute_importance(headline: str, topics: List[str]) -> float:
    """
    Compute real-world technology significance and impact score.
    Independent from confidence and temporal freshness.
    """
    combined_text = f"{headline} {' '.join(topics)}"
    score = BASE_IMPORTANCE

    # Check high-impact boosts
    for pattern, boost in HIGH_IMPACT_PATTERNS:
        if pattern.search(combined_text):
            score += boost
            break  # Apply top matched high-impact signal

    # Check low-impact penalties
    for pattern, penalty in LOW_IMPACT_PATTERNS:
        if pattern.search(combined_text):
            score += penalty
            break

    return round(max(0.10, min(1.0, score)), 3)


def compute_novelty(timeline_count: int, source_count: int) -> float:
    """
    Compute novelty score representing how new/unprecedented the story is.
    Decays gradually as subsequent updates and corroborations accumulate.
    """
    if timeline_count <= 1 and source_count <= 1:
        return 1.0

    timeline_decay = max(0, timeline_count - 1) * TIMELINE_DECAY_STEP
    source_decay = max(0, source_count - 1) * SOURCE_DECAY_STEP
    novelty = BASE_NOVELTY - timeline_decay - source_decay

    return round(max(MIN_NOVELTY, min(1.0, novelty)), 3)


def compute_event_freshness(first_seen: datetime, sources: List[EventSourceEvidence]) -> Tuple[FreshnessLevel, float]:
    """
    Compute categorical FreshnessLevel and continuous freshness_score [0.0, 1.0].
    Uses earliest observation time or earliest publication time.
    """
    now_utc = datetime.now(UTC)
    
    # Identify most authoritative published or discovered timestamp
    timestamps = [first_seen]
    for s in sources:
        if s.published_at is not None:
            timestamps.append(s.published_at)
        else:
            timestamps.append(s.discovered_at)

    earliest_time = min(timestamps)
    if earliest_time.tzinfo is None:
        earliest_time = earliest_time.replace(tzinfo=UTC)

    delta = now_utc - earliest_time
    age_minutes = max(0.0, delta.total_seconds() / 60.0)

    level = FreshnessLevel.from_age_minutes(age_minutes)

    if age_minutes <= 5.0:
        score = 1.00
    elif age_minutes <= 30.0:
        score = 0.90
    elif age_minutes <= 120.0:
        score = 0.75
    elif age_minutes <= 360.0:
        score = 0.50
    elif age_minutes <= 1440.0:
        score = 0.30
    elif age_minutes <= 4320.0:
        score = 0.10
    else:
        score = 0.00

    return level, score


class ScoringEngine:
    """
    Stage 8: Implements PipelineStage[TechEvent, TechEvent].
    
    Calculates confidence, importance, novelty, freshness, and derives is_breaking.
    """

    @property
    def name(self) -> str:
        return "scoring_engine"

    @property
    def stage_number(self) -> int:
        return 8

    async def process(
        self,
        input_item: TechEvent,
        context: PipelineContext,
    ) -> Optional[TechEvent]:
        """
        Score a canonical TechEvent and update its attributes.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, TechEvent):
            raise DomainValidationError(f"ScoringEngine expects TechEvent, got {type(input_item)}")

        # 1. Compute Confidence
        confidence = compute_confidence(input_item.sources)
        input_item.confidence = confidence

        # 2. Compute Importance
        importance = compute_importance(input_item.headline, input_item.topics)
        input_item.importance = importance

        # 3. Compute Novelty
        novelty = compute_novelty(len(input_item.timeline), input_item.source_count)
        input_item.novelty = novelty

        # 4. Compute Freshness & Freshness Score
        freshness_level, freshness_score = compute_event_freshness(
            input_item.first_seen, input_item.sources
        )
        input_item.freshness = freshness_level
        input_item.freshness_score = freshness_score

        # 5. Record diagnostic metrics in context
        context.set("scoring_metrics", {
            "confidence": confidence,
            "importance": importance,
            "novelty": novelty,
            "freshness": freshness_level.value,
            "freshness_score": freshness_score,
            "is_breaking": input_item.is_breaking,
        })

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
