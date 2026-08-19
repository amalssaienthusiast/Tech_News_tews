"""
Processing module for news article pipeline.

Provides:
- Multi-method deduplication engine
- Content classification
- Metadata enrichment
- Quality filtering
"""

from src.processing.deduplication import (
    DeduplicationEngine,
    TitleSimilarityChecker,
    ContentHasher,
)

__all__ = [
    "DeduplicationEngine",
    "TitleSimilarityChecker",
    "ContentHasher",
]
