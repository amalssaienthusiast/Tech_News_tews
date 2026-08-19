"""
Stage 10: Persistence Stage.
Location: src/pipeline/stages/s10_persistence.py

Persists canonical TechEvent updates into the underlying event repository/storage:
- Interfaces cleanly with existing repository contracts
- Zero schema modifications or storage internal changes in Phase 3
- Sets context metadata 'persisted_at'
"""

from __future__ import annotations

from datetime import datetime, UTC
import logging
import time
from typing import Any, Callable, Dict, Optional

from ...domain.models import TechEvent
from ...domain.validators import DomainValidationError
from ...storage.protocols import EventRepositoryProtocol
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)


class PersistenceStage:
    """
    Stage 10: Implements PipelineStage[TechEvent, TechEvent].
    
    Persists or updates TechEvent aggregates in the canonical repository or fallback store.
    """

    def __init__(
        self,
        repository: Optional[EventRepositoryProtocol] = None,
        persistence_fn: Optional[Callable[[TechEvent], Any]] = None,
    ):
        self._repository = repository
        self._persistence_fn = persistence_fn
        # In-memory backing store for testing / standalone operation
        self._store: Dict[str, TechEvent] = {}

    @property
    def name(self) -> str:
        return "persistence_stage"

    @property
    def stage_number(self) -> int:
        return 10

    @property
    def repository(self) -> Optional[EventRepositoryProtocol]:
        return self._repository

    @property
    def store(self) -> Dict[str, TechEvent]:
        return self._store

    async def process(
        self,
        input_item: TechEvent,
        context: PipelineContext,
    ) -> Optional[TechEvent]:
        """
        Persist TechEvent state to the backing repository or fallback store.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, TechEvent):
            raise DomainValidationError(f"PersistenceStage expects TechEvent, got {type(input_item)}")

        now_utc = datetime.now(UTC)

        try:
            if self._repository is not None:
                await self._repository.save_event(input_item)
            elif self._persistence_fn is not None:
                res = self._persistence_fn(input_item)
                if hasattr(res, "__await__"):
                    await res
            else:
                self._store[input_item.id] = input_item

            context.set("persisted_at", now_utc.isoformat())
        except Exception as e:
            logger.error(f"PersistenceStage failed to persist event '{input_item.id}': {e}")
            raise

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
