"""
Stage 7: Event Clusterer.
Location: src/pipeline/stages/s07_clustering.py

Aggregates NormalizedArticle instances into canonical TechEvent aggregate roots:
- Correlates multi-source articles into evolving events
- Applies 48-hour active temporal matching window
- Uses deterministic SHA-256 event identity
- Transitions lifecycle: SUSPECTED -> CORROBORATED -> CONFIRMED (NO ACTIVE)
- Maintains chronological TimelineEntry updates and deduplicated EventSourceEvidence
- Strictly leaves scoring (confidence/importance/novelty/breaking) to Stage 8

Zero legacy event clusterer modification. Completely isolated canonical stage.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, UTC, timedelta
import hashlib
import logging
import re
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from ...domain.enums import EventStatus, FreshnessLevel, SourceTier
from ...domain.models import NormalizedArticle, TechEvent, EventSourceEvidence, TimelineEntry
from ...domain.validators import DomainValidationError
from ...storage.protocols import EventRepositoryProtocol
from ..protocols import PipelineStage, PipelineContext
from .s05_dedup_evaluator import extract_title_shingles, compute_jaccard_similarity

logger = logging.getLogger(__name__)

TEMPORAL_WINDOW_HOURS = 48.0
CLUSTERING_SIMILARITY_THRESHOLD = 0.55
MAX_ACTIVE_EVENTS = 5000


def make_event_id(headline: str, first_seen: datetime) -> str:
    """
    Generate deterministic SHA-256 event identifier based on headline and first_seen date.
    """
    date_str = first_seen.strftime("%Y-%m-%d")
    normalized_headline = re.sub(r"\s+", " ", headline.lower().strip())
    raw = f"event:{normalized_headline}|{date_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ActiveEventStore:
    """
    Thread-safe, memory-bounded store for active TechEvent aggregates within the 48-hour window.
    """

    def __init__(self, max_capacity: int = MAX_ACTIVE_EVENTS, window_hours: float = TEMPORAL_WINDOW_HOURS):
        self._max_capacity = max_capacity
        self._window_hours = window_hours
        self._lock = threading.RLock()
        # event_id -> TechEvent
        self._events: OrderedDict[str, TechEvent] = OrderedDict()
        # event_id -> precomputed shingle set
        self._event_shingles: Dict[str, Set[str]] = {}

    def find_matching_event(self, article: NormalizedArticle, now_utc: datetime) -> Tuple[Optional[TechEvent], float]:
        """
        Find an existing active TechEvent that correlates with this article within the 48h window.
        Returns (matched_event, similarity_score).
        """
        with self._lock:
            self._prune_expired_events(now_utc)

            article_shingles = extract_title_shingles(article.title)
            article_entities = set(e.lower() for e in article.tags)
            if "entities" in article.metadata and isinstance(article.metadata["entities"], dict):
                for entity_list in article.metadata["entities"].values():
                    article_entities.update(str(e).lower() for e in entity_list)

            best_match: Optional[TechEvent] = None
            best_sim = 0.0

            cutoff = now_utc - timedelta(hours=self._window_hours)

            for event_id, event in self._events.items():
                if event.last_updated < cutoff:
                    continue

                shingles = self._event_shingles.get(event_id, set())
                title_sim = compute_jaccard_similarity(article_shingles, shingles)

                # Check entity overlap bonus
                event_entities = set(e.lower() for e in event.entities + event.topics)
                entity_overlap = len(article_entities & event_entities) if article_entities and event_entities else 0
                effective_sim = title_sim + (0.10 if entity_overlap >= 1 else 0.0)

                if effective_sim > best_sim:
                    best_sim = effective_sim
                    best_match = event

            if best_sim >= CLUSTERING_SIMILARITY_THRESHOLD and best_match is not None:
                return best_match, best_sim

            return None, 0.0

    def put_event(self, event: TechEvent) -> None:
        """Store or update an active event in the store."""
        with self._lock:
            if event.id not in self._events and len(self._events) >= self._max_capacity:
                oldest_id, _ = self._events.popitem(last=False)
                self._event_shingles.pop(oldest_id, None)

            self._events[event.id] = event
            self._event_shingles[event.id] = extract_title_shingles(event.headline)

    def get_event(self, event_id: str) -> Optional[TechEvent]:
        with self._lock:
            return self._events.get(event_id)

    def _prune_expired_events(self, now_utc: datetime) -> None:
        """Prune events inactive beyond the temporal window."""
        cutoff = now_utc - timedelta(hours=self._window_hours)
        expired_ids = [eid for eid, ev in self._events.items() if ev.last_updated < cutoff]
        for eid in expired_ids:
            self._events.pop(eid, None)
            self._event_shingles.pop(eid, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._event_shingles.clear()

    async def hydrate(
        self,
        repository: EventRepositoryProtocol,
        window_hours: Optional[float] = None,
    ) -> int:
        """
        Hydrate active events from the canonical repository on startup.

        Fetches events where last_updated >= (now - window_hours), populates
        the store, and precomputes all title shingles. Returns count of hydrated events.
        """
        target_window = window_hours if window_hours is not None else self._window_hours
        cutoff_utc = datetime.now(UTC) - timedelta(hours=target_window)

        events = await repository.get_events_since(cutoff_utc=cutoff_utc, limit=self._max_capacity)

        with self._lock:
            for event in events:
                if not isinstance(event, TechEvent):
                    continue
                # Ensure capacity
                if event.id not in self._events and len(self._events) >= self._max_capacity:
                    oldest_id, _ = self._events.popitem(last=False)
                    self._event_shingles.pop(oldest_id, None)

                self._events[event.id] = event
                self._event_shingles[event.id] = extract_title_shingles(event.headline)

        logger.info(f"S07 ActiveEventStore hydrated {len(events)} active events (Window: {target_window}h).")
        return len(events)


class EventClusterer:
    """
    Stage 7: Implements PipelineStage[NormalizedArticle, TechEvent].
    
    Correlates NormalizedArticle into a canonical TechEvent aggregate root.
    """

    def __init__(self, store: Optional[ActiveEventStore] = None):
        self._store = ActiveEventStore() if store is None else store

    @property
    def store(self) -> ActiveEventStore:
        return self._store

    @property
    def name(self) -> str:
        return "event_clusterer"

    @property
    def stage_number(self) -> int:
        return 7

    async def hydrate(
        self,
        repository: EventRepositoryProtocol,
        window_hours: Optional[float] = None,
    ) -> int:
        """Proxy hydration call to the underlying ActiveEventStore."""
        return await self._store.hydrate(repository, window_hours=window_hours)

    async def process(
        self,
        input_item: NormalizedArticle,
        context: PipelineContext,
    ) -> Optional[TechEvent]:
        """
        Process an article into a new or updated TechEvent.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, NormalizedArticle):
            raise DomainValidationError(f"EventClusterer expects NormalizedArticle, got {type(input_item)}")

        now_utc = input_item.discovered_at or datetime.now(UTC)

        # 1. Build immutable source evidence
        evidence = EventSourceEvidence(
            article_id=input_item.id,
            url=input_item.canonical_url,
            title=input_item.title,
            source_name=input_item.source_name,
            source_tier=input_item.source_tier,
            discovered_at=input_item.discovered_at,
            published_at=input_item.published_at,
            summary=input_item.summary,
            image_url=input_item.image_url,
            is_primary=(input_item.source_tier == SourceTier.TIER_1_PREMIUM),
        )

        # 2. Check for matching active event
        matched_event, sim_score = self._store.find_matching_event(input_item, now_utc)

        if matched_event is not None:
            # Update existing event
            is_new_source = matched_event.add_source(evidence)
            if is_new_source:
                # Add timeline entry
                entry = TimelineEntry(
                    timestamp=input_item.discovered_at,
                    headline=input_item.title,
                    source_name=input_item.source_name,
                    source_url=input_item.canonical_url,
                    confidence_at_time=0.50,
                    entry_type="corroboration",
                )
                matched_event.add_timeline_entry(entry)

                # Status transitions (SUSPECTED -> CORROBORATED -> CONFIRMED)
                if matched_event.status == EventStatus.SUSPECTED and matched_event.source_count >= 2:
                    matched_event.status = EventStatus.CORROBORATED
                if input_item.source_tier == SourceTier.TIER_1_PREMIUM:
                    matched_event.status = EventStatus.CONFIRMED

                # Merge topics/entities
                for tag in input_item.tags:
                    if tag not in matched_event.topics:
                        matched_event.topics.append(tag)

            event = matched_event
            context.set("clustering_action", "merged_existing")
            context.set("clustering_similarity", round(sim_score, 3))
        else:
            # Create new canonical TechEvent
            event_id = make_event_id(input_item.title, input_item.discovered_at)
            
            # Initial status
            initial_status = (
                EventStatus.CONFIRMED
                if input_item.source_tier == SourceTier.TIER_1_PREMIUM
                else EventStatus.SUSPECTED
            )

            initial_entry = TimelineEntry(
                timestamp=input_item.discovered_at,
                headline=input_item.title,
                source_name=input_item.source_name,
                source_url=input_item.canonical_url,
                confidence_at_time=0.30 if initial_status == EventStatus.CONFIRMED else 0.15,
                entry_type="initial",
            )

            event = TechEvent(
                id=event_id,
                headline=input_item.title,
                first_seen=input_item.discovered_at,
                last_updated=input_item.discovered_at,
                entities=list(input_item.authors),
                topics=list(input_item.tags),
                sources=[evidence],
                primary_source=input_item.source_name if evidence.is_primary else None,
                confidence=0.0,    # Stage 8 calculates confidence
                importance=0.5,    # Stage 8 calculates importance
                novelty=1.0,       # Stage 8 calculates novelty
                status=initial_status,
                freshness=FreshnessLevel.FRESH,
                freshness_score=1.0,
                timeline=[initial_entry],
                cluster_id=event_id,
                category=input_item.metadata.get("category"),
            )
            context.set("clustering_action", "created_new")
            context.set("clustering_similarity", 0.0)

        # 3. Store active event in store
        self._store.put_event(event)
        context.set("event_id", event.id)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return event
