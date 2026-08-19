"""
SQLite User Preferences Repository — Canonical Implementation.
Location: src/storage/sqlite_user_preferences_repository.py

Implements UserPreferencesRepositoryProtocol for UserPreferences personalization entities:
- Persists user preferences, topic subscriptions, company watchlist, and source preferences.
- Manages bookmarked articles and reading history.
- Enforces strict foreign key relations, UTC datetime normalization, and atomic transactions.
- Zero legacy storage dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import aiosqlite

from src.domain.validators import DomainValidationError
from src.user.preferences import (
    AlertThresholds,
    CompanyWatchItem,
    DeliverySettings,
    SourcePreference,
    TopicSubscription,
    UserPreferences,
)
from .protocols import UserPreferencesRepositoryProtocol
from .sqlite_engine import SqliteEngine

logger = logging.getLogger(__name__)


def _normalize_datetime(dt: Optional[datetime], field_name: str) -> Optional[datetime]:
    """Validate that datetime is timezone-aware and convert to UTC."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        raise DomainValidationError(f"Field '{field_name}' must be a datetime, got {type(dt)}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise DomainValidationError(f"Field '{field_name}' must be timezone-aware (UTC), got naive datetime")
    return dt.astimezone(UTC)


class SqliteUserPreferencesRepository(UserPreferencesRepositoryProtocol):
    """
    Asynchronous SQLite repository for user personalization and preferences.
    """

    def __init__(self, engine: SqliteEngine, auto_init: bool = True) -> None:
        self.engine = engine
        self._auto_init = auto_init
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """Initialize schema idempotently on first call if auto_init is enabled."""
        if not self._auto_init or self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await self.engine.initialize_schema()
                self._initialized = True

    async def save_preferences(self, preferences: UserPreferences) -> None:
        """
        Upsert a complete UserPreferences aggregate along with its topic subscriptions,
        company watchlist, and source preferences atomically.
        """
        if not isinstance(preferences, UserPreferences):
            raise DomainValidationError(f"Expected UserPreferences instance, got {type(preferences)}")

        await self._ensure_initialized()

        created_at = _normalize_datetime(preferences.created_at, "created_at") or datetime.now(UTC)
        updated_at = _normalize_datetime(preferences.updated_at, "updated_at") or datetime.now(UTC)

        delivery_json = json.dumps(preferences.delivery.model_dump())
        alerts_json = json.dumps(preferences.alerts.model_dump())

        async with self.engine.transaction() as conn:
            # 1. Upsert user_preferences root table
            upsert_root_sql = """
            INSERT INTO user_preferences (
                user_id, display_name, theme, articles_per_page,
                reading_history_enabled, delivery_settings, alert_thresholds,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name,
                theme = excluded.theme,
                articles_per_page = excluded.articles_per_page,
                reading_history_enabled = excluded.reading_history_enabled,
                delivery_settings = excluded.delivery_settings,
                alert_thresholds = excluded.alert_thresholds,
                updated_at = excluded.updated_at;
            """
            await conn.execute(
                upsert_root_sql,
                (
                    preferences.user_id,
                    preferences.display_name,
                    preferences.theme,
                    preferences.articles_per_page,
                    1 if preferences.reading_history_enabled else 0,
                    delivery_json,
                    alerts_json,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )

            # 2. Synchronize user_topics child table
            await conn.execute("DELETE FROM user_topics WHERE user_id = ?;", (preferences.user_id,))
            if preferences.topics:
                topic_rows = [
                    (
                        preferences.user_id,
                        t.topic,
                        t.weight,
                        json.dumps(t.keywords),
                        1 if t.enabled else 0,
                    )
                    for t in preferences.topics
                ]
                await conn.executemany(
                    """
                    INSERT INTO user_topics (user_id, topic, weight, keywords, enabled)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    topic_rows,
                )

            # 3. Synchronize user_watchlist child table
            await conn.execute("DELETE FROM user_watchlist WHERE user_id = ?;", (preferences.user_id,))
            if preferences.watchlist:
                watch_rows = [
                    (
                        preferences.user_id,
                        w.name,
                        w.ticker,
                        json.dumps(w.aliases),
                        w.priority,
                        1 if w.enabled else 0,
                    )
                    for w in preferences.watchlist
                ]
                await conn.executemany(
                    """
                    INSERT INTO user_watchlist (user_id, company_name, ticker, aliases, priority, enabled)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    watch_rows,
                )

            # 4. Synchronize user_sources child table
            await conn.execute("DELETE FROM user_sources WHERE user_id = ?;", (preferences.user_id,))
            if preferences.sources:
                source_rows = [
                    (
                        preferences.user_id,
                        s.source_domain,
                        s.source_name,
                        1 if s.preferred else 0,
                        1 if s.blocked else 0,
                        s.trust_score,
                    )
                    for s in preferences.sources
                ]
                await conn.executemany(
                    """
                    INSERT INTO user_sources (user_id, source_domain, source_name, preferred, blocked, trust_score)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    source_rows,
                )

    async def get_preferences(self, user_id: str) -> Optional[UserPreferences]:
        """
        Load a complete UserPreferences aggregate by user_id. Returns None if not found.
        """
        await self._ensure_initialized()

        async with self.engine.connect() as conn:
            # 1. Fetch root preferences
            root_cursor = await conn.execute(
                "SELECT * FROM user_preferences WHERE user_id = ?;",
                (user_id,),
            )
            root_row = await root_cursor.fetchone()
            if not root_row:
                return None

            created_at = datetime.fromisoformat(root_row["created_at"]).astimezone(UTC)
            updated_at = datetime.fromisoformat(root_row["updated_at"]).astimezone(UTC)

            raw_delivery = json.loads(root_row["delivery_settings"]) if root_row["delivery_settings"] else {}
            raw_alerts = json.loads(root_row["alert_thresholds"]) if root_row["alert_thresholds"] else {}

            delivery = DeliverySettings(**raw_delivery)
            alerts = AlertThresholds(**raw_alerts)

            # 2. Fetch topics
            topics_cursor = await conn.execute(
                "SELECT topic, weight, keywords, enabled FROM user_topics WHERE user_id = ? ORDER BY id ASC;",
                (user_id,),
            )
            topic_rows = await topics_cursor.fetchall()
            topics = [
                TopicSubscription(
                    topic=r["topic"],
                    weight=r["weight"],
                    keywords=json.loads(r["keywords"]) if r["keywords"] else [],
                    enabled=bool(r["enabled"]),
                )
                for r in topic_rows
            ]

            # 3. Fetch watchlist
            watch_cursor = await conn.execute(
                "SELECT company_name, ticker, aliases, priority, enabled FROM user_watchlist WHERE user_id = ? ORDER BY id ASC;",
                (user_id,),
            )
            watch_rows = await watch_cursor.fetchall()
            watchlist = [
                CompanyWatchItem(
                    name=r["company_name"],
                    ticker=r["ticker"],
                    aliases=json.loads(r["aliases"]) if r["aliases"] else [],
                    priority=r["priority"],
                    enabled=bool(r["enabled"]),
                )
                for r in watch_rows
            ]

            # 4. Fetch source preferences
            sources_cursor = await conn.execute(
                "SELECT source_domain, source_name, preferred, blocked, trust_score FROM user_sources WHERE user_id = ? ORDER BY id ASC;",
                (user_id,),
            )
            source_rows = await sources_cursor.fetchall()
            sources = [
                SourcePreference(
                    source_domain=r["source_domain"],
                    source_name=r["source_name"] or "",
                    preferred=bool(r["preferred"]),
                    blocked=bool(r["blocked"]),
                    trust_score=r["trust_score"],
                )
                for r in source_rows
            ]

            return UserPreferences(
                user_id=root_row["user_id"],
                display_name=root_row["display_name"],
                theme=root_row["theme"],
                articles_per_page=root_row["articles_per_page"],
                reading_history_enabled=bool(root_row["reading_history_enabled"]),
                topics=topics,
                watchlist=watchlist,
                sources=sources,
                delivery=delivery,
                alerts=alerts,
                created_at=created_at,
                updated_at=updated_at,
            )

    async def add_user_bookmark(
        self,
        user_id: str,
        article_id: str,
        title: str,
        url: str,
        source: str = "",
        notes: str = "",
    ) -> None:
        """
        Add or update a bookmarked article for a user.
        """
        await self._ensure_initialized()
        upsert_sql = """
        INSERT INTO user_bookmarks (user_id, article_id, title, url, source, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, article_id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            source = excluded.source,
            notes = excluded.notes;
        """
        async with self.engine.transaction() as conn:
            await conn.execute(upsert_sql, (user_id, article_id, title, url, source, notes))

    async def get_user_bookmarks(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all bookmarked articles for a user ordered by created_at DESC.
        """
        await self._ensure_initialized()
        sql = """
        SELECT article_id, title, url, source, notes, created_at
        FROM user_bookmarks
        WHERE user_id = ?
        ORDER BY created_at DESC;
        """
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, (user_id,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def remove_user_bookmark(self, user_id: str, article_id: str) -> bool:
        """
        Remove a bookmarked article for a user. Returns True if removed, False otherwise.
        """
        await self._ensure_initialized()
        sql = "DELETE FROM user_bookmarks WHERE user_id = ? AND article_id = ?;"
        async with self.engine.transaction() as conn:
            cursor = await conn.execute(sql, (user_id, article_id))
            return cursor.rowcount > 0

    async def add_reading_history(
        self,
        user_id: str,
        article_id: str,
        read_at: Optional[datetime] = None,
        time_spent_seconds: int = 0,
        clicked_links: int = 0,
    ) -> None:
        """
        Record an article reading interaction in user history.
        """
        await self._ensure_initialized()
        read_at_utc = _normalize_datetime(read_at, "read_at") or datetime.now(UTC)
        sql = """
        INSERT INTO user_reading_history (user_id, article_id, read_at, time_spent_seconds, clicked_links)
        VALUES (?, ?, ?, ?, ?);
        """
        async with self.engine.transaction() as conn:
            await conn.execute(
                sql,
                (user_id, article_id, read_at_utc.isoformat(), time_spent_seconds, clicked_links),
            )

    async def get_reading_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent reading history records for a user ordered by read_at DESC.
        """
        await self._ensure_initialized()
        safe_limit = max(1, min(limit, 500))
        sql = """
        SELECT article_id, read_at, time_spent_seconds, clicked_links
        FROM user_reading_history
        WHERE user_id = ?
        ORDER BY read_at DESC
        LIMIT ?;
        """
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, (user_id, safe_limit))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def delete_user_data(self, user_id: str) -> Dict[str, int]:
        """
        Atomically delete all stored data (preferences, topics, watchlist, sources,
        bookmarks, reading history) for a given user. Returns per-table deletion counts.
        """
        await self._ensure_initialized()
        counts: Dict[str, int] = {}

        tables = [
            ("user_topics", "user_topics"),
            ("user_watchlist", "user_watchlist"),
            ("user_sources", "user_sources"),
            ("user_bookmarks", "user_bookmarks"),
            ("user_reading_history", "user_reading_history"),
            ("user_preferences", "user_preferences"),
        ]

        async with self.engine.transaction() as conn:
            for table_name, dict_key in tables:
                cursor = await conn.execute(
                    f"DELETE FROM {table_name} WHERE user_id = ?;",
                    (user_id,),
                )
                counts[dict_key] = cursor.rowcount

        return counts
