"""
Stage 6: Deduplication Committer.
Location: src/pipeline/stages/s06_dedup_committer.py

Atomically commits approved unique articles to the deduplication index:
- Commits ONLY when:
    quality_report.is_passed == True
    AND
    dedup_decision.action == DedupAction.ACCEPTED
    AND
    not dedup_decision.is_duplicate
- NEVER commits rejected, low-quality, or duplicate articles.
- Eliminates dedup poisoning.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple, Union

from ...domain.enums import DedupAction
from ...domain.models import NormalizedArticle, QualityReport, DedupDecision
from ...domain.validators import DomainValidationError
from ..protocols import PipelineStage, PipelineContext
from .s05_dedup_evaluator import DedupIndex

logger = logging.getLogger(__name__)


class DedupCommitter:
    """
    Stage 6: Implements PipelineStage[NormalizedArticle, NormalizedArticle].
    
    Atomically commits approved articles to the DedupIndex.
    """

    def __init__(self, index: DedupIndex):
        if not isinstance(index, DedupIndex):
            raise DomainValidationError(f"DedupCommitter requires DedupIndex instance, got {type(index)}")
        self._index = index

    @property
    def index(self) -> DedupIndex:
        return self._index

    @property
    def name(self) -> str:
        return "dedup_committer"

    @property
    def stage_number(self) -> int:
        return 6

    async def process(
        self,
        input_item: NormalizedArticle,
        context: PipelineContext,
    ) -> Optional[NormalizedArticle]:
        """
        Conditionally commit article to the dedup index.
        Returns the article if successfully committed or eligible, None if ineligible.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, NormalizedArticle):
            raise DomainValidationError(f"DedupCommitter expects NormalizedArticle, got {type(input_item)}")

        # 1. Retrieve QualityReport and DedupDecision from context
        quality_report: Optional[QualityReport] = context.get("quality_report")
        dedup_decision: Optional[DedupDecision] = context.get("dedup_decision")

        # 2. Gate verification: Must be high quality AND accepted unique
        is_quality_passed = (quality_report is not None and quality_report.is_passed)
        is_dedup_accepted = (
            dedup_decision is not None
            and dedup_decision.action == DedupAction.ACCEPTED
            and not dedup_decision.is_duplicate
        )

        if not is_quality_passed:
            context.set("dedup_committed", False)
            logger.debug(f"Article '{input_item.id}' skipped dedup commit (failed quality check)")
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.record_metric(self.name, elapsed_ms)
            return None

        if not is_dedup_accepted:
            context.set("dedup_committed", False)
            logger.debug(f"Article '{input_item.id}' skipped dedup commit (not unique/accepted)")
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.record_metric(self.name, elapsed_ms)
            return None

        # 3. Atomic, idempotent commit
        self._index.commit(
            canonical_url=input_item.canonical_url,
            title=input_item.title,
            article_id=input_item.id,
        )

        context.set("dedup_committed", True)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
