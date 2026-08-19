"""
Canonical Pipeline Package (Phase 3).
Location: src/pipeline/__init__.py

Exports canonical pipeline runner, protocols, adapters, and stage implementations.
"""

from .protocols import PipelineStage, PipelineContext
from .adapters import SourceObservationAdapter
from .runner import CanonicalPipelineRunner, IngestionResult, IngestionStatus

__all__ = [
    "PipelineStage",
    "PipelineContext",
    "SourceObservationAdapter",
    "CanonicalPipelineRunner",
    "IngestionResult",
    "IngestionStatus",
]
