"""
Events API routes (Phase 5D-A).
Location: src/api/routes/events.py

Exposes RESTful endpoints and SSE streams for TechEvent aggregate roots:
- Backed by asynchronous EventRepositoryProtocol (SqliteEventRepository)
- Canonical DTO mapping via TechEventResponse.from_domain()
- Subscribes to PublicationBus for real-time event updates
- Zero direct SQLite / SQL dependencies in this layer
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.auth import verify_api_key
from src.domain.enums import PublicationChannel, PublicationEventType
from src.domain.models import EventSourceEvidence, PublicationEvent, TechEvent, TimelineEntry
from src.engine.publication_bus import get_publication_bus
from src.storage.protocols import EventRepositoryProtocol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/events", tags=["Events"])


# =============================================================================
# REPOSITORY DEPENDENCY INJECTION
# =============================================================================

_shared_repository: Optional[EventRepositoryProtocol] = None


def get_event_repository() -> EventRepositoryProtocol:
    """
    Get the shared EventRepositoryProtocol dependency.
    Raises RuntimeError if not configured via set_event_repository().
    """
    global _shared_repository
    if _shared_repository is None:
        raise RuntimeError(
            "EventRepository has not been initialized. "
            "Call set_event_repository(repo) during application startup."
        )
    return _shared_repository


def set_event_repository(repository: Optional[EventRepositoryProtocol]) -> None:
    """Inject the canonical EventRepositoryProtocol implementation."""
    global _shared_repository
    _shared_repository = repository


# =============================================================================
# RESPONSE MODELS / DTOs
# =============================================================================

class TimelineEntryResponse(BaseModel):
    timestamp: str
    headline: str
    source_name: str
    source_url: str
    confidence_at_time: float
    entry_type: str

    @classmethod
    def from_domain(cls, entry: TimelineEntry) -> TimelineEntryResponse:
        return cls(
            timestamp=entry.timestamp.isoformat(),
            headline=entry.headline,
            source_name=entry.source_name,
            source_url=entry.source_url,
            confidence_at_time=float(entry.confidence_at_time),
            entry_type=str(entry.entry_type),
        )


class EventSourceResponseModel(BaseModel):
    title: str
    url: str
    source_name: str
    is_primary: bool

    @classmethod
    def from_domain(cls, source: EventSourceEvidence) -> EventSourceResponseModel:
        return cls(
            title=source.title,
            url=source.url,
            source_name=source.source_name,
            is_primary=bool(source.is_primary),
        )


class TechEventResponse(BaseModel):
    id: str
    headline: str
    first_seen: str
    last_updated: str
    entities: List[str]
    topics: List[str]
    confidence: float
    status: str
    freshness: str
    freshness_score: float
    source_count: int
    primary_source: Optional[str] = None
    timeline: List[TimelineEntryResponse]
    sources: List[EventSourceResponseModel]

    @classmethod
    def from_domain(cls, event: TechEvent) -> TechEventResponse:
        return cls(
            id=event.id,
            headline=event.headline,
            first_seen=event.first_seen.isoformat(),
            last_updated=event.last_updated.isoformat(),
            entities=list(event.entities),
            topics=list(event.topics),
            confidence=float(event.confidence),
            status=event.status.value if hasattr(event.status, "value") else str(event.status),
            freshness=event.freshness.value if hasattr(event.freshness, "value") else str(event.freshness),
            freshness_score=float(event.freshness_score),
            source_count=event.source_count,
            primary_source=event.primary_source,
            timeline=[TimelineEntryResponse.from_domain(t) for t in event.timeline],
            sources=[EventSourceResponseModel.from_domain(s) for s in event.sources],
        )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", response_model=List[TechEventResponse])
async def get_events(
    limit: int = Query(50, ge=1, le=200, description="Number of events to retrieve"),
    entity: Optional[str] = Query(None, max_length=100, description="Filter by entity"),
    auth: dict = Depends(verify_api_key),
    repo: EventRepositoryProtocol = Depends(get_event_repository),
) -> List[TechEventResponse]:
    """Get active tech events, optionally filtered by entity."""
    try:
        if entity:
            events = await repo.get_events_by_entity(entity, limit=limit)
        else:
            events = await repo.get_active_events(limit=limit)

        return [TechEventResponse.from_domain(e) for e in events]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving events from repository: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal event storage error")


@router.get("/stats", response_model=Dict[str, Any])
async def get_event_stats(
    auth: dict = Depends(verify_api_key),
    repo: EventRepositoryProtocol = Depends(get_event_repository),
) -> Dict[str, Any]:
    """Get event store diagnostic statistics."""
    try:
        return await repo.get_stats()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving event stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal event storage error")


@router.get("/stream")
async def event_stream(
    request: Request,
    repo: EventRepositoryProtocol = Depends(get_event_repository),
):
    """Server-Sent Events (SSE) endpoint for real-time breaking event updates.

    Subscribes directly to the application PublicationBus (SSE_STREAM channel).
    """
    bus = get_publication_bus()
    sub_id, client_queue = await bus.subscribe(channels=(PublicationChannel.SSE_STREAM,))

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    # Wait for next publication event
                    pub_event = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    if pub_event is None:  # Shutdown sentinel
                        break

                    event = None
                    if isinstance(pub_event.payload, TechEvent):
                        event = pub_event.payload
                    elif isinstance(pub_event.payload, dict) and "id" in pub_event.payload:
                        event = await repo.get_event(pub_event.payload["id"])
                    elif isinstance(pub_event.payload, str):
                        event = await repo.get_event(pub_event.payload)

                    if event:
                        data = TechEventResponse.from_domain(event).model_dump_json()
                        yield f"event: event_update\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield 'event: ping\ndata: {"ping": true}\n\n'
        finally:
            await bus.unsubscribe(sub_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{event_id}", response_model=TechEventResponse)
async def get_event_by_id(
    event_id: str,
    auth: dict = Depends(verify_api_key),
    repo: EventRepositoryProtocol = Depends(get_event_repository),
) -> TechEventResponse:
    """Get a single tech event by ID."""
    try:
        event = await repo.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
        return TechEventResponse.from_domain(event)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving event '{event_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal event storage error")


def broadcast_event_update(event_id: str) -> None:
    """Call this when an event aggregate is updated.

    Pushes to PublicationBus to notify all connected subscribers.
    """
    try:
        bus = get_publication_bus()
        event = PublicationEvent(
            event_type=PublicationEventType.EVENT_UPDATED,
            payload={"id": event_id},
            channels=(PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT),
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(bus.publish(event))
        except RuntimeError:
            pass
    except Exception:
        pass
