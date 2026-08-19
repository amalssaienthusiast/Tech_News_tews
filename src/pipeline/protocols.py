"""
Canonical Pipeline Stage Protocols and Execution Context.
Location: src/pipeline/protocols.py

Defines the abstract interface for all stages in the Canonical Sequential Pipeline (Phase 3).
Zero external dependencies; strictly typed and thread/async-safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
import logging
from typing import Any, Dict, Generic, Optional, Protocol, TypeVar, runtime_checkable
from uuid import uuid4

logger = logging.getLogger(__name__)

T_in = TypeVar("T_in", contravariant=True)
T_out = TypeVar("T_out", covariant=True)


@dataclass(slots=True)
class PipelineContext:
    """
    Carries execution-scoped diagnostic and tracing state through pipeline stages.
    
    Scoped strictly to a single pipeline invocation. Does NOT create global state.
    """
    pipeline_id: str = field(default_factory=lambda: uuid4().hex[:16])
    correlation_id: str = field(default_factory=lambda: uuid4().hex[:16])
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = field(default_factory=dict)
    stage_metrics: Dict[str, float] = field(default_factory=dict)  # stage_name -> latency_ms
    is_aborted: bool = False
    abort_reason: Optional[str] = None

    def record_metric(self, stage_name: str, latency_ms: float) -> None:
        """Record the execution latency in milliseconds for a specific stage."""
        self.stage_metrics[stage_name] = round(latency_ms, 3)

    def abort(self, reason: str) -> None:
        """Mark the pipeline execution as aborted (e.g. due to filtering or deduplication)."""
        self.is_aborted = True
        self.abort_reason = reason
        logger.debug(f"Pipeline {self.pipeline_id} aborted: {reason}")

    def set(self, key: str, value: Any) -> None:
        """Store an item in context metadata."""
        self.metadata[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve an item from context metadata."""
        return self.metadata.get(key, default)


@runtime_checkable
class PipelineStage(Protocol[T_in, T_out]):
    """
    Abstract Protocol defining the contract for every stage in the canonical pipeline.
    
    Stages must be side-effect free on their inputs and return the transformed output
    or None if the item is discarded by the stage.
    """

    @property
    def name(self) -> str:
        """Human-readable identifier of the pipeline stage."""
        ...

    @property
    def stage_number(self) -> int:
        """Numeric index of the stage in the canonical sequence (1 through 11)."""
        ...

    async def process(self, input_item: T_in, context: PipelineContext) -> Optional[T_out]:
        """
        Process a single item through this pipeline stage.
        
        Args:
            input_item: Strongly-typed input contract for this stage.
            context: Diagnostic and execution tracing context.
            
        Returns:
            Transformed output item, or None if dropped/filtered by this stage.
        """
        ...
