"""
SQLite Event Repository — Canonical Event Brain Persistence.
Location: src/storage/sqlite_event_repository.py

Implements EventRepositoryProtocol using SqliteEngine:
- Atomic TechEvent aggregate root persistence (root, sources, timeline)
- Complete round-trip domain fidelity (frozen models, UTC datetimes, enums)
- Safe parameterized queries and transaction rollback
- Zero external ORM or web framework dependencies
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
import logging
from typing import Any, Dict, List, Optional

import aiosqlite

from src.domain.enums import EventStatus, FreshnessLevel, SourceTier
from src.domain.models import EventSourceEvidence, TechEvent, TimelineEntry
from src.domain.validators import DomainValidationError
from .protocols import EventRepositoryProtocol
from .sqlite_engine import SqliteEngine

logger = logging.getLogger(__name__)


def _parse_utc_datetime(val: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string ensuring a timezone-aware UTC datetime."""
    if not val:
        return None
    val_clean = val.strip()
    if val_clean.endswith("Z"):
        val_clean = val_clean[:-1] + "+00:00"
    dt = datetime.fromisoformat(val_clean)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_source_tier(val: Any) -> SourceTier:
    """Parse source tier safely whether stored as integer or legacy string."""
    if isinstance(val, SourceTier):
        return val
    try:
        return SourceTier(int(val))
    except (ValueError, TypeError):
        if isinstance(val, str):
            val_clean = val.strip().lower()
            if "1" in val_clean or "premium" in val_clean:
                return SourceTier.TIER_1_PREMIUM
            elif "2" in val_clean or "specialist" in val_clean:
                return SourceTier.TIER_2_SPECIALIST
            elif "3" in val_clean or "community" in val_clean:
                return SourceTier.TIER_3_COMMUNITY
            elif "4" in val_clean or "discovery" in val_clean:
                return SourceTier.TIER_4_DISCOVERY
        return SourceTier.TIER_2_SPECIALIST


class SqliteEventRepository(EventRepositoryProtocol):
    """
    SQLite-backed repository for TechEvent aggregate roots.
    """

    def __init__(self, engine: Optional[SqliteEngine] = None, auto_init: bool = True) -> None:
        self.engine = engine or SqliteEngine()
        self._auto_init = auto_init
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazily initialize schema if configured."""
        if self._auto_init and not self._initialized:
            await self.engine.initialize_schema()
            self._initialized = True

    async def save_event(self, event: TechEvent) -> None:
        """
        Upsert a TechEvent aggregate root along with all its sources and timeline
        entries within a single atomic transaction.
        """
        if not isinstance(event, TechEvent):
            raise DomainValidationError(f"Expected TechEvent instance, got {type(event)}")

        await self._ensure_initialized()

        async with self.engine.transaction() as conn:
            # 1. Upsert TechEvent Aggregate Root
            await conn.execute(
                """
                INSERT INTO canonical_events (
                    id, headline, first_seen, last_updated,
                    entities, topics, primary_source, confidence,
                    importance, novelty, status, freshness,
                    freshness_score, cluster_id, category, source_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    headline = excluded.headline,
                    last_updated = excluded.last_updated,
                    entities = excluded.entities,
                    topics = excluded.topics,
                    primary_source = excluded.primary_source,
                    confidence = excluded.confidence,
                    importance = excluded.importance,
                    novelty = excluded.novelty,
                    status = excluded.status,
                    freshness = excluded.freshness,
                    freshness_score = excluded.freshness_score,
                    cluster_id = excluded.cluster_id,
                    category = excluded.category,
                    source_count = excluded.source_count;
                """,
                (
                    event.id,
                    event.headline,
                    event.first_seen.isoformat(),
                    event.last_updated.isoformat(),
                    json.dumps(event.entities),
                    json.dumps(event.topics),
                    event.primary_source,
                    event.confidence,
                    event.importance,
                    event.novelty,
                    event.status.value,
                    event.freshness.value,
                    event.freshness_score,
                    event.cluster_id,
                    event.category,
                    event.source_count,
                ),
            )

            # 2. Upsert Child Sources (EventSourceEvidence)
            for source in event.sources:
                await conn.execute(
                    """
                    INSERT INTO canonical_event_sources (
                        event_id, article_id, url, title, source_name,
                        source_tier, discovered_at, published_at, summary,
                        image_url, is_primary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, url) DO UPDATE SET
                        title = excluded.title,
                        source_name = excluded.source_name,
                        source_tier = excluded.source_tier,
                        published_at = excluded.published_at,
                        summary = excluded.summary,
                        image_url = excluded.image_url,
                        is_primary = excluded.is_primary;
                    """,
                    (
                        event.id,
                        source.article_id,
                        source.url,
                        source.title,
                        source.source_name,
                        source.source_tier.value,
                        source.discovered_at.isoformat(),
                        source.published_at.isoformat() if source.published_at else None,
                        source.summary,
                        source.image_url,
                        1 if source.is_primary else 0,
                    ),
                )

            # 3. Synchronize Child Timeline (TimelineEntry)
            # Recreate timeline entries for this aggregate to ensure exact parity
            await conn.execute(
                "DELETE FROM canonical_event_timeline WHERE event_id = ?;",
                (event.id,),
            )

            if event.timeline:
                timeline_rows = [
                    (
                        event.id,
                        entry.timestamp.isoformat(),
                        entry.headline,
                        entry.source_name,
                        entry.source_url,
                        entry.confidence_at_time,
                        entry.entry_type,
                    )
                    for entry in event.timeline
                ]
                await conn.executemany(
                    """
                    INSERT INTO canonical_event_timeline (
                        event_id, timestamp, headline, source_name, source_url,
                        confidence_at_time, entry_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    timeline_rows,
                )

    async def get_event(self, event_id: str) -> Optional[TechEvent]:
        """Load a complete TechEvent aggregate by ID."""
        await self._ensure_initialized()

        async with self.engine.connect() as conn:
            cur = await conn.execute("SELECT * FROM canonical_events WHERE id = ?;", (event_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return await self._hydrate_event(conn, row)

    async def get_active_events(self, limit: int = 100) -> List[TechEvent]:
        """Query non-stale TechEvent aggregates ordered by last_updated DESC."""
        await self._ensure_initialized()

        async with self.engine.connect() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM canonical_events
                WHERE status != 'stale'
                ORDER BY last_updated DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = await cur.fetchall()
            return [await self._hydrate_event(conn, row) for row in rows]

    async def get_events_since(
        self,
        cutoff_utc: datetime,
        limit: int = 5000,
    ) -> List[TechEvent]:
        """
        Fetch active TechEvent aggregates where last_updated >= cutoff_utc
        ordered by last_updated ASC for S07 clustering cold-start hydration.
        """
        await self._ensure_initialized()
        cutoff_iso = cutoff_utc.isoformat()

        async with self.engine.connect() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM canonical_events
                WHERE last_updated >= ?
                ORDER BY last_updated ASC
                LIMIT ?;
                """,
                (cutoff_iso, limit),
            )
            rows = await cur.fetchall()
            return [await self._hydrate_event(conn, row) for row in rows]

    async def get_events_by_entity(
        self,
        entity: str,
        limit: int = 50,
    ) -> List[TechEvent]:
        """Filter TechEvent aggregates that mention a specific entity."""
        await self._ensure_initialized()
        normalized_entity = entity.strip().lower()

        async with self.engine.connect() as conn:
            try:
                # Use JSON1 extension json_each for exact array value matching
                cur = await conn.execute(
                    """
                    SELECT DISTINCT e.* FROM canonical_events e, json_each(e.entities) j
                    WHERE LOWER(j.value) = ?
                    ORDER BY e.last_updated DESC
                    LIMIT ?;
                    """,
                    (normalized_entity, limit),
                )
                rows = await cur.fetchall()
            except Exception:
                # Fallback to LIKE if json_each is not available
                cur = await conn.execute(
                    """
                    SELECT * FROM canonical_events
                    WHERE LOWER(entities) LIKE ?
                    ORDER BY last_updated DESC
                    LIMIT ?;
                    """,
                    (f"%{normalized_entity}%", limit),
                )
                rows = await cur.fetchall()

            return [await self._hydrate_event(conn, row) for row in rows]

    async def delete_event(self, event_id: str) -> bool:
        """
        Delete a TechEvent by ID, cascading deletion to all child sources
        and timeline entries.
        """
        await self._ensure_initialized()

        async with self.engine.transaction() as conn:
            cur = await conn.execute("DELETE FROM canonical_events WHERE id = ?;", (event_id,))
            return cur.rowcount > 0

    async def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic store statistics."""
        await self._ensure_initialized()

        async with self.engine.connect() as conn:
            total_events = (await (await conn.execute("SELECT COUNT(*) FROM canonical_events;")).fetchone())[0]
            active_events = (
                await (
                    await conn.execute("SELECT COUNT(*) FROM canonical_events WHERE status != 'stale';")
                ).fetchone()
            )[0]
            total_sources = (
                await (await conn.execute("SELECT COUNT(*) FROM canonical_event_sources;")).fetchone()
            )[0]
            total_timeline = (
                await (await conn.execute("SELECT COUNT(*) FROM canonical_event_timeline;")).fetchone()
            )[0]

            status_counts = {}
            for row in await (
                await conn.execute("SELECT status, COUNT(*) as cnt FROM canonical_events GROUP BY status;")
            ).fetchall():
                status_counts[row["status"]] = row["cnt"]

            freshness_counts = {}
            for row in await (
                await conn.execute("SELECT freshness, COUNT(*) as cnt FROM canonical_events GROUP BY freshness;")
            ).fetchall():
                freshness_counts[row["freshness"]] = row["cnt"]

            return {
                "total_events": total_events,
                "active_events": active_events,
                "total_sources": total_sources,
                "total_timeline_entries": total_timeline,
                "status_breakdown": status_counts,
                "freshness_breakdown": freshness_counts,
                "db_path": str(self.engine.db_path),
            }

    async def _hydrate_event(self, conn: aiosqlite.Connection, row: aiosqlite.Row) -> TechEvent:
        """Convert a database row and its child entities into a canonical TechEvent."""
        event_id = row["id"]

        # Load child sources
        cur = await conn.execute(
            "SELECT * FROM canonical_event_sources WHERE event_id = ? ORDER BY discovered_at ASC;",
            (event_id,),
        )
        source_rows = await cur.fetchall()

        sources: List[EventSourceEvidence] = []
        for sr in source_rows:
            sources.append(
                EventSourceEvidence(
                    article_id=sr["article_id"],
                    url=sr["url"],
                    title=sr["title"],
                    source_name=sr["source_name"],
                    source_tier=_parse_source_tier(sr["source_tier"]),
                    discovered_at=_parse_utc_datetime(sr["discovered_at"]),  # type: ignore
                    published_at=_parse_utc_datetime(sr["published_at"]),
                    summary=sr["summary"] or "",
                    image_url=sr["image_url"],
                    is_primary=bool(sr["is_primary"]),
                )
            )

        # Load child timeline
        cur = await conn.execute(
            "SELECT * FROM canonical_event_timeline WHERE event_id = ? ORDER BY timestamp ASC;",
            (event_id,),
        )
        timeline_rows = await cur.fetchall()

        timeline: List[TimelineEntry] = []
        for tr in timeline_rows:
            timeline.append(
                TimelineEntry(
                    timestamp=_parse_utc_datetime(tr["timestamp"]),  # type: ignore
                    headline=tr["headline"],
                    source_name=tr["source_name"],
                    source_url=tr["source_url"],
                    confidence_at_time=float(tr["confidence_at_time"]),
                    entry_type=tr["entry_type"],
                )
            )

        return TechEvent(
            id=event_id,
            headline=row["headline"],
            first_seen=_parse_utc_datetime(row["first_seen"]),  # type: ignore
            last_updated=_parse_utc_datetime(row["last_updated"]),  # type: ignore
            entities=json.loads(row["entities"]) if row["entities"] else [],
            topics=json.loads(row["topics"]) if row["topics"] else [],
            sources=sources,
            primary_source=row["primary_source"],
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            novelty=float(row["novelty"]),
            status=EventStatus(row["status"]),
            freshness=FreshnessLevel(row["freshness"]),
            freshness_score=float(row["freshness_score"]),
            timeline=timeline,
            cluster_id=row["cluster_id"] or "",
            category=row["category"],
        )
