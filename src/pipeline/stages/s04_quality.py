"""
Stage 4: Quality Gate.
Location: src/pipeline/stages/s04_quality.py

Evaluates technical hygiene, content length, clickbait, spam, and boilerplate.
Produces the canonical QualityReport model combining quality_score and relevance_score.

Guarantees:
- quality_score in [0.0, 1.0]
- relevance_score in [0.0, 1.0] (preserved separately from Stage 3)
- If is_passed is False, rejection_reasons is strictly non-empty.
"""

from __future__ import annotations

from datetime import datetime, UTC
import logging
import re
import time
from typing import List, Optional, Tuple

from ...domain.enums import QualityCheckLevel
from ...domain.models import NormalizedArticle, QualityReport
from ...domain.validators import DomainValidationError
from ..protocols import PipelineStage, PipelineContext
from .s03_relevance import RelevanceResult

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 0.50
RELEVANCE_THRESHOLD = 0.40

# Clickbait / Sensationalism regex triggers
CLICKBAIT_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\byou won'?t believe\b", re.IGNORECASE),
    re.compile(r"\bthis one trick\b", re.IGNORECASE),
    re.compile(r"\bwhat happens next\b", re.IGNORECASE),
    re.compile(r"\bwill blow your mind\b", re.IGNORECASE),
    re.compile(r"\bshocking (truth|secret|discovery)\b", re.IGNORECASE),
    re.compile(r"\bexperts are terrified\b", re.IGNORECASE),
    re.compile(r"[!?]{3,}"),  # Extreme multiple punctuation (e.g. !!! or ???)
)

# Paywall / Truncation markers
PAYWALL_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\bsubscribe to read the (full|rest)\b", re.IGNORECASE),
    re.compile(r"\bsubscribers only\b", re.IGNORECASE),
    re.compile(r"\blog in or register to view\b", re.IGNORECASE),
    re.compile(r"\bcontinue reading in our app\b", re.IGNORECASE),
    re.compile(r"\breading this requires a premium subscription\b", re.IGNORECASE),
)


def evaluate_content_hygiene(
    title: str,
    clean_text: str = "",
    summary: str = "",
    check_level: QualityCheckLevel = QualityCheckLevel.STANDARD,
) -> Tuple[float, Tuple[str, ...]]:
    """
    Evaluates technical quality hygiene and returns (quality_score, rejection_reasons).
    """
    reasons: List[str] = []
    penalties = 0.0

    total_text = f"{clean_text} {summary}".strip()
    words = total_text.split() if total_text else []
    word_count = len(words)

    # 1. Content Length Check
    if word_count < 15 and not summary:
        penalties += 0.45
        reasons.append("EXTREMELY_SHORT_CONTENT")
    elif word_count < 30:
        penalties += 0.25
        reasons.append("LOW_WORD_COUNT")

    # 2. ALL CAPS Headline Check
    letters = [c for c in title if c.isalpha()]
    if len(letters) >= 10:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio > 0.70:
            penalties += 0.30
            reasons.append("ALL_CAPS_HEADLINE")

    # 3. Clickbait Headline Patterns
    for pattern in CLICKBAIT_PATTERNS:
        if pattern.search(title):
            penalties += 0.35
            reasons.append("CLICKBAIT_HEADLINE")
            break

    # 4. Paywall / Truncation Patterns
    for pattern in PAYWALL_PATTERNS:
        if pattern.search(clean_text) or pattern.search(summary):
            penalties += 0.30
            reasons.append("PAYWALL_TRUNCATED")
            break

    # 5. Strict Check Level Penalties
    if check_level == QualityCheckLevel.STRICT and word_count < 60:
        penalties += 0.20
        reasons.append("STRICT_LENGTH_REQUIREMENT_UNMET")

    raw_score = 1.0 - penalties
    final_quality_score = round(max(0.05, min(1.0, raw_score)), 3)

    return final_quality_score, tuple(reasons)


class QualityGate:
    """
    Stage 4: Implements PipelineStage[NormalizedArticle, Tuple[NormalizedArticle, QualityReport]].
    
    Evaluates quality and generates the canonical QualityReport.
    """

    def __init__(self, check_level: QualityCheckLevel = QualityCheckLevel.STANDARD):
        self._check_level = check_level

    @property
    def name(self) -> str:
        return "quality_gate"

    @property
    def stage_number(self) -> int:
        return 4

    async def process(
        self,
        input_item: NormalizedArticle,
        context: PipelineContext,
    ) -> Optional[Tuple[NormalizedArticle, QualityReport]]:
        """
        Process quality evaluation. Combines with Stage 3 relevance result.
        Returns (article, QualityReport) if passed, or None if failed.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, NormalizedArticle):
            raise DomainValidationError(f"QualityGate expects NormalizedArticle, got {type(input_item)}")

        # 1. Retrieve Stage 3 relevance result from context (or default)
        rel_result: Optional[RelevanceResult] = context.get("relevance_result")
        if rel_result is not None:
            relevance_score = rel_result.relevance_score
            matched_keywords = rel_result.matched_keywords
            detected_categories = rel_result.detected_categories
        else:
            relevance_score = 0.50
            matched_keywords = ()
            detected_categories = ()

        # 2. Evaluate quality hygiene
        quality_score, quality_reasons = evaluate_content_hygiene(
            title=input_item.title,
            clean_text=input_item.clean_text,
            summary=input_item.summary,
            check_level=self._check_level,
        )

        all_reasons: List[str] = list(quality_reasons)
        if relevance_score < RELEVANCE_THRESHOLD:
            all_reasons.append("OFF_TOPIC")

        is_passed = (quality_score >= QUALITY_THRESHOLD) and (relevance_score >= RELEVANCE_THRESHOLD)

        # Invariant: If is_passed is False, rejection_reasons MUST NOT be empty
        if not is_passed and not all_reasons:
            all_reasons.append("BELOW_QUALITY_THRESHOLD")

        # 3. Create Canonical QualityReport
        report = QualityReport(
            article_id=input_item.id,
            is_passed=is_passed,
            quality_score=quality_score,
            relevance_score=relevance_score,
            check_level=self._check_level,
            rejection_reasons=tuple(all_reasons) if not is_passed else (),
            matched_keywords=matched_keywords,
            detected_categories=detected_categories,
            evaluated_at=datetime.now(UTC),
        )

        context.set("quality_report", report)

        if not is_passed:
            context.abort(f"Article '{input_item.id}' failed QualityGate: {report.rejection_reasons}")
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.record_metric(self.name, elapsed_ms)
            return None

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item, report
