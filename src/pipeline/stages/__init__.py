"""
Canonical Pipeline Stages Package.
Location: src/pipeline/stages/__init__.py

Exports Stage 1 through Stage 11 implementations.
"""

from .s01_normalizer import ObservationNormalizer, clean_headline_text, clean_summary_text
from .s02_freshness import FreshnessEvaluator, FreshnessResult, calculate_freshness_score
from .s03_relevance import TechRelevanceFilter, RelevanceResult, evaluate_tech_relevance
from .s04_quality import QualityGate, evaluate_content_hygiene
from .s05_dedup_evaluator import (
    DedupIndex,
    DedupEvaluator,
    extract_title_shingles,
    compute_jaccard_similarity,
)
from .s06_dedup_committer import DedupCommitter
from .s07_clustering import (
    EventClusterer,
    ActiveEventStore,
    make_event_id,
)
from .s08_scoring import (
    ScoringEngine,
    compute_confidence,
    compute_importance,
    compute_novelty,
    compute_event_freshness,
)
from .s09_enrichment import EnrichmentStage
from .s10_persistence import PersistenceStage
from .s11_publication import PublicationStage

__all__ = [
    "ObservationNormalizer",
    "clean_headline_text",
    "clean_summary_text",
    "FreshnessEvaluator",
    "FreshnessResult",
    "calculate_freshness_score",
    "TechRelevanceFilter",
    "RelevanceResult",
    "evaluate_tech_relevance",
    "QualityGate",
    "evaluate_content_hygiene",
    "DedupIndex",
    "DedupEvaluator",
    "extract_title_shingles",
    "compute_jaccard_similarity",
    "DedupCommitter",
    "EventClusterer",
    "ActiveEventStore",
    "make_event_id",
    "ScoringEngine",
    "compute_confidence",
    "compute_importance",
    "compute_novelty",
    "compute_event_freshness",
    "EnrichmentStage",
    "PersistenceStage",
    "PublicationStage",
]
