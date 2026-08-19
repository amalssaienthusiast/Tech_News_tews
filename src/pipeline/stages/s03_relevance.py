"""
Stage 3: Technology Relevance Filter.
Location: src/pipeline/stages/s03_relevance.py

Evaluates domain relevance for technology, computer science, and engineering content.
Keeps technology relevance ownership strictly separated from technical quality/hygiene.

Produces:
- relevance_score in [0.0, 1.0]
- detected_categories: Tuple[str, ...]
- matched_keywords: Tuple[str, ...]
- is_relevant: bool (threshold >= 0.40)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import logging
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from ...domain.models import NormalizedArticle
from ...domain.validators import DomainValidationError
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)

RELEVANCE_THRESHOLD = 0.40

# Category taxonomy and keyword maps
TECH_TAXONOMY: Dict[str, Tuple[str, ...]] = {
    "AI_ML": (
        "artificial intelligence", "machine learning", "deep learning", "neural network",
        "llm", "large language model", "transformer", "openai", "anthropic", "gpt",
        "gemini", "claude", "pytorch", "tensorflow", "diffusion model", "generative ai",
        "prompt engineering", "ai agent", "reinforcement learning",
    ),
    "CYBERSECURITY": (
        "vulnerability", "zero-day", "ransomware", "malware", "exploit", "cve",
        "security patch", "cyberattack", "infosec", "ddos", "phishing", "encryption",
        "cryptography", "backdoor", "breach", "threat actor", "hacker", "pen testing",
    ),
    "CLOUD_INFRA": (
        "kubernetes", "docker", "container", "aws", "azure", "gcp", "serverless",
        "devops", "ci/cd", "microservices", "terraform", "linux", "cloud computing",
        "distributed systems", "load balancer", "kafka", "redis", "postgresql",
    ),
    "SOFTWARE_ENG": (
        "python", "rust", "golang", "javascript", "typescript", "c++", "compiler",
        "framework", "database", "nosql", "rest api", "graphql", "git", "architecture",
        "open source", "sdk", "backend", "frontend", "algorithm", "data structure",
    ),
    "HARDWARE_CHIPS": (
        "semiconductor", "gpu", "cpu", "nvidia", "amd", "intel", "tsmc", "arm",
        "qualcomm", "quantum computing", "asic", "risc-v", "transistor", "silicon",
        "chipset", "motherboard", "microcontroller",
    ),
    "EMERGING_TECH": (
        "robotics", "autonomous vehicle", "lidar", "biotech", "crispr", "telecom",
        "5g", "6g", "iot", "augmented reality", "virtual reality", "aerospace",
        "drone", "clean tech", "satellite",
    ),
}

# Explicit non-tech exclusions
EXCLUSIONS: Tuple[str, ...] = (
    "celebrity gossip", "horoscope", "astrology", "weight loss", "fashion trend",
    "red carpet", "casino bonus", "sports score", "premier league", "nfl draft",
    "soap opera", "hollywood romance", "lottery numbers", "recipe for",
)


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    """Diagnostic outcome of technology relevance evaluation."""
    relevance_score: float
    is_relevant: bool
    detected_categories: Tuple[str, ...]
    matched_keywords: Tuple[str, ...]
    evaluated_at: datetime


def evaluate_tech_relevance(
    title: str,
    clean_text: str = "",
    summary: str = "",
    tags: Tuple[str, ...] = (),
) -> RelevanceResult:
    """
    Evaluate tech relevance based on multi-field weighted pattern matching:
    - Title matches: 3x weight
    - Summary & Tags: 2x weight
    - Body text: 1x weight
    """
    now_utc = datetime.now(UTC)
    combined_title = title.lower()
    combined_summary = summary.lower()
    combined_body = clean_text[:3000].lower()
    combined_tags = " ".join(tags).lower()

    # 1. Non-tech exclusion check
    for excl in EXCLUSIONS:
        if excl in combined_title or excl in combined_tags:
            return RelevanceResult(
                relevance_score=0.10,
                is_relevant=False,
                detected_categories=(),
                matched_keywords=(f"exclusion:{excl}",),
                evaluated_at=now_utc,
            )

    matched_keywords_set: Set[str] = set()
    detected_categories_set: Set[str] = set()
    raw_score_points = 0.0

    # 2. Tech Taxonomy Matching
    for category, keywords in TECH_TAXONOMY.items():
        category_matched = False
        for kw in keywords:
            # Word boundary regex for single words, direct substring for phrases
            if " " in kw:
                pattern = re.escape(kw)
            else:
                pattern = rf"\b{re.escape(kw)}\b"

            # Check title (3.0 pts)
            if re.search(pattern, combined_title):
                matched_keywords_set.add(kw)
                detected_categories_set.add(category)
                category_matched = True
                raw_score_points += 3.0

            # Check summary & tags (2.0 pts)
            elif re.search(pattern, combined_summary) or re.search(pattern, combined_tags):
                matched_keywords_set.add(kw)
                detected_categories_set.add(category)
                category_matched = True
                raw_score_points += 2.0

            # Check body text (1.0 pts)
            elif re.search(pattern, combined_body):
                matched_keywords_set.add(kw)
                detected_categories_set.add(category)
                category_matched = True
                raw_score_points += 1.0

    # 3. Score calculation
    # Base mapping: 0 pts -> 0.15, 3 pts (1 title match) -> 0.65, 6+ pts -> 0.85-1.00
    if not matched_keywords_set:
        final_score = 0.15
    else:
        num_kw = len(matched_keywords_set)
        num_cats = len(detected_categories_set)
        base = min(0.95, 0.45 + (raw_score_points * 0.08) + (num_cats * 0.05))
        final_score = round(base, 3)

    is_relevant = final_score >= RELEVANCE_THRESHOLD

    return RelevanceResult(
        relevance_score=final_score,
        is_relevant=is_relevant,
        detected_categories=tuple(sorted(detected_categories_set)),
        matched_keywords=tuple(sorted(matched_keywords_set)),
        evaluated_at=now_utc,
    )


class TechRelevanceFilter:
    """
    Stage 3: Implements PipelineStage[NormalizedArticle, NormalizedArticle].
    
    Evaluates technology relevance and filters out off-topic content.
    """

    @property
    def name(self) -> str:
        return "tech_relevance_filter"

    @property
    def stage_number(self) -> int:
        return 3

    async def process(
        self,
        input_item: NormalizedArticle,
        context: PipelineContext,
    ) -> Optional[NormalizedArticle]:
        """
        Process technology relevance scoring.
        Stores RelevanceResult in context. Aborts and returns None if below threshold.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, NormalizedArticle):
            raise DomainValidationError(f"TechRelevanceFilter expects NormalizedArticle, got {type(input_item)}")

        result = evaluate_tech_relevance(
            title=input_item.title,
            clean_text=input_item.clean_text,
            summary=input_item.summary,
            tags=input_item.tags,
        )

        context.set("relevance_result", result)

        if not result.is_relevant:
            context.abort(
                f"Article '{input_item.id}' rejected by TechRelevanceFilter "
                f"(score {result.relevance_score:.2f} < {RELEVANCE_THRESHOLD:.2f})"
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.record_metric(self.name, elapsed_ms)
            return None

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
