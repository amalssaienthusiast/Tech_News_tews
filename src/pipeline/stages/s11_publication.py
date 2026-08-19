"""
Stage 11: Publication Stage.
Location: src/pipeline/stages/s11_publication.py

Dispatches scored and enriched TechEvent aggregates to the application-scoped PublicationBus:
- Constructs canonical PublicationEvent domain model
- Assigns PublicationPriority.HIGH when TechEvent.is_breaking is True
- Targets SSE_STREAM and TELEGRAM_BOT publication channels
- Sets deterministic idempotency keys to prevent publication duplication
- Sets context metadata 'published_channels' and 'publication_priority'
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ...domain.enums import PublicationChannel, PublicationEventType, PublicationPriority
from ...domain.models import TechEvent, PublicationEvent
from ...domain.validators import DomainValidationError
from ...engine.publication_bus import PublicationBus, get_publication_bus
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)


class PublicationStage:
    """
    Stage 11: Implements PipelineStage[TechEvent, TechEvent].
    
    Publishes TechEvent to the application PublicationBus.
    """

    def __init__(self, bus: Optional[PublicationBus] = None):
        self._bus = bus if bus is not None else get_publication_bus()

    @property
    def bus(self) -> PublicationBus:
        return self._bus

    @property
    def name(self) -> str:
        return "publication_stage"

    @property
    def stage_number(self) -> int:
        return 11

    async def process(
        self,
        input_item: TechEvent,
        context: PipelineContext,
    ) -> Optional[TechEvent]:
        """
        Construct and dispatch PublicationEvent to the application PublicationBus.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, TechEvent):
            raise DomainValidationError(f"PublicationStage expects TechEvent, got {type(input_item)}")

        # 1. Determine Event Type & Priority
        event_type = (
            PublicationEventType.EVENT_DETECTED
            if input_item.source_count <= 1
            else PublicationEventType.EVENT_UPDATED
        )
        priority = (
            PublicationPriority.HIGH
            if input_item.is_breaking
            else PublicationPriority.NORMAL
        )

        channels = (PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT)
        idempotency_key = f"pub:{input_item.id}:{input_item.last_updated.isoformat()}"

        # 2. Construct Canonical PublicationEvent
        pub_event = PublicationEvent(
            event_type=event_type,
            payload=input_item,
            channels=channels,
            priority=priority,
            idempotency_key=idempotency_key,
        )

        # 3. Publish to application bus
        dispatched_count = await self._bus.publish(pub_event)

        # 4. Context Metadata & Metrics
        context.set("published_channels", [c.value for c in channels])
        context.set("publication_priority", priority.value)
        context.set("subscribers_dispatched", dispatched_count)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return input_item
