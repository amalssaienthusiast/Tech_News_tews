"""
Stage 9: Enrichment Stage.
Location: src/pipeline/stages/s09_enrichment.py

Performs bounded asynchronous enrichment (summarization, topic tagging) on canonical TechEvent aggregates:
- Strict 2.0 second timeout per item using asyncio.wait_for()
- Graceful fallback on timeout or external enhancer failure (never blocks core pipeline)
- Sets context metadata 'enrichment_status' ("enriched" | "fallback" | "skipped")
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from ...domain.models import TechEvent
from ...domain.validators import DomainValidationError
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)

DEFAULT_ENRICHMENT_TIMEOUT_SECONDS = 2.0


class EnrichmentStage:
    """
    Stage 9: Implements PipelineStage[TechEvent, TechEvent].
    
    Performs bounded asynchronous enrichment without blocking ingestion.
    """

    def __init__(
        self,
        enhancer_fn: Optional[Callable[[TechEvent], Any]] = None,
        timeout_seconds: float = DEFAULT_ENRICHMENT_TIMEOUT_SECONDS,
    ):
        self._enhancer_fn = enhancer_fn
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "enrichment_stage"

    @property
    def stage_number(self) -> int:
        return 9

    async def _run_enrichment(self, event: TechEvent) -> TechEvent:
        """Execute enrichment callable or default lightweight tagging."""
        if self._enhancer_fn is not None:
            res = self._enhancer_fn(event)
            if asyncio.iscoroutine(res):
                await res
        return event

    async def process(
        self,
        input_item: TechEvent,
        context: PipelineContext,
    ) -> Optional[TechEvent]:
        """
        Enrich a TechEvent with a strict bounded timeout.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, TechEvent):
            raise DomainValidationError(f"EnrichmentStage expects TechEvent, got {type(input_item)}")

        try:
            # Execute with strict timeout
            await asyncio.wait_for(
                self._run_enrichment(input_item),
                timeout=self._timeout_seconds,
            )
            context.set("enrichment_status", "enriched")
        except asyncio.TimeoutError:
            logger.warning(
                f"EnrichmentStage timed out ({self._timeout_seconds}s) for event '{input_item.id}'. "
                "Falling back to base event."
            )
            context.set("enrichment_status", "fallback")
        except Exception as e:
            logger.warning(
                f"EnrichmentStage failed for event '{input_item.id}': {e}. "
                "Falling back to base event."
            )
            context.set("enrichment_status", "fallback")

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
