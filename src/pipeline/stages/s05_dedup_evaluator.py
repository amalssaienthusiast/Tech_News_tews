"""
Stage 5: Deduplication Evaluator.
Location: src/pipeline/stages/s05_dedup_evaluator.py

Performs READ-ONLY evaluation against the deduplication index:
- Exact canonical URL match -> EXACT_URL_DUPLICATE
- Title Jaccard/MinHash similarity (threshold >= 0.80) -> SIMILAR_TITLE_DUPLICATE
- Unique -> ACCEPTED

Guarantees:
- ZERO state mutation during evaluate().
- Thread and async safe read-only operations.
- Application-scoped index dependency injection.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, UTC
import hashlib
import logging
import re
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from ...domain.enums import DedupAction
from ...domain.models import NormalizedArticle, DedupDecision
from ...domain.validators import DomainValidationError
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.70
MAX_INDEX_CAPACITY = 20000


def extract_title_shingles(title: str, k: int = 2) -> Set[str]:
    """Extract word unigrams and bigrams from headline for robust Jaccard comparison."""
    words = [w for w in re.findall(r"\w+", title.lower()) if len(w) > 0]
    if not words:
        return set()
    unigrams = set(words)
    bigrams = {" ".join(words[i:i+2]) for i in range(len(words) - 1)} if len(words) >= 2 else set()
    return unigrams | bigrams


def compute_jaccard_similarity(s1: Set[str], s2: Set[str]) -> float:
    """Compute Jaccard similarity coefficient between two sets."""
    if not s1 or not s2:
        return 0.0
    intersection = len(s1 & s2)
    union = len(s1 | s2)
    return intersection / union if union > 0 else 0.0


class DedupIndex:
    """
    Thread-safe, bounded in-memory deduplication index.
    Supports separate read-only evaluation and atomic commit.
    """

    def __init__(self, max_capacity: int = MAX_INDEX_CAPACITY):
        self._max_capacity = max_capacity
        self._lock = threading.RLock()
        # canonical_url -> article_id
        self._url_index: OrderedDict[str, str] = OrderedDict()
        # article_id -> (canonical_url, title_shingles)
        self._article_index: OrderedDict[str, Tuple[str, Set[str]]] = OrderedDict()

    def evaluate(self, canonical_url: str, title: str, article_id: str) -> DedupDecision:
        """
        READ-ONLY evaluation of an article against current index state.
        Never mutates the index.
        """
        with self._lock:
            # 1. Exact Canonical URL Check
            if canonical_url in self._url_index:
                matched_id = self._url_index[canonical_url]
                return DedupDecision(
                    article_id=article_id,
                    action=DedupAction.EXACT_URL_DUPLICATE,
                    is_duplicate=True,
                    canonical_url=canonical_url,
                    matched_article_id=matched_id,
                    similarity_score=1.0,
                    evaluated_at=datetime.now(UTC),
                )

            # 2. Similar Title Check (Shingle Jaccard)
            incoming_shingles = extract_title_shingles(title)
            best_match_id: Optional[str] = None
            best_similarity = 0.0

            if incoming_shingles:
                for indexed_art_id, (_, indexed_shingles) in self._article_index.items():
                    sim = compute_jaccard_similarity(incoming_shingles, indexed_shingles)
                    if sim > best_similarity:
                        best_similarity = sim
                        best_match_id = indexed_art_id

            if best_similarity >= SIMILARITY_THRESHOLD and best_match_id is not None:
                return DedupDecision(
                    article_id=article_id,
                    action=DedupAction.SIMILAR_TITLE_DUPLICATE,
                    is_duplicate=True,
                    canonical_url=canonical_url,
                    matched_article_id=best_match_id,
                    similarity_score=round(best_similarity, 3),
                    evaluated_at=datetime.now(UTC),
                )

            # 3. Unique & Accepted
            return DedupDecision(
                article_id=article_id,
                action=DedupAction.ACCEPTED,
                is_duplicate=False,
                canonical_url=canonical_url,
                matched_article_id=None,
                similarity_score=0.0,
                evaluated_at=datetime.now(UTC),
            )

    def commit(self, canonical_url: str, title: str, article_id: str) -> bool:
        """
        Atomic commit of an approved unique article to the index.
        """
        with self._lock:
            # Idempotent write
            if canonical_url in self._url_index and self._url_index[canonical_url] == article_id:
                return True

            # Evict oldest if capacity reached
            if len(self._url_index) >= self._max_capacity:
                oldest_url, oldest_id = self._url_index.popitem(last=False)
                self._article_index.pop(oldest_id, None)

            shingles = extract_title_shingles(title)
            self._url_index[canonical_url] = article_id
            self._article_index[article_id] = (canonical_url, shingles)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._url_index)

    def clear(self) -> None:
        with self._lock:
            self._url_index.clear()
            self._article_index.clear()


class DedupEvaluator:
    """
    Stage 5: Implements PipelineStage[NormalizedArticle, Tuple[NormalizedArticle, DedupDecision]].
    
    Evaluates deduplication in READ-ONLY mode.
    """

    def __init__(self, index: Optional[DedupIndex] = None):
        self._index = DedupIndex() if index is None else index

    @property
    def index(self) -> DedupIndex:
        return self._index

    @property
    def name(self) -> str:
        return "dedup_evaluator"

    @property
    def stage_number(self) -> int:
        return 5

    async def process(
        self,
        input_item: NormalizedArticle,
        context: PipelineContext,
    ) -> Optional[Tuple[NormalizedArticle, DedupDecision]]:
        """
        Evaluate deduplication without modifying the index.
        Stores DedupDecision in context. Aborts context and returns None if duplicate.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, NormalizedArticle):
            raise DomainValidationError(f"DedupEvaluator expects NormalizedArticle, got {type(input_item)}")

        decision = self._index.evaluate(
            canonical_url=input_item.canonical_url,
            title=input_item.title,
            article_id=input_item.id,
        )

        context.set("dedup_decision", decision)

        if decision.is_duplicate:
            context.abort(
                f"Article '{input_item.id}' rejected as duplicate: {decision.action.value} "
                f"(matched: {decision.matched_article_id}, similarity: {decision.similarity_score:.2f})"
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.record_metric(self.name, elapsed_ms)
            return None

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item, decision
