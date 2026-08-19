"""
Storage Protocols — Canonical Repository Interfaces.
Location: src/storage/protocols.py

Defines abstract asynchronous repository interfaces for domain models:
- EventRepositoryProtocol (TechEvent aggregate root, EventSourceEvidence, TimelineEntry)
- ArticleRepositoryProtocol (NormalizedArticle)
- SourceHealthRepositoryProtocol (SourceHealth)

Strictly typed against canonical domain models in src.domain.models.
Zero external ORM or web framework dependencies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from src.domain.models import (
    ArticleSearchResult,
    NormalizedArticle,
    SourceHealth,
    TechEvent,
)


@runtime_checkable
class EventRepositoryProtocol(Protocol):
    """Asynchronous repository interface for TechEvent aggregate roots."""

    async def save_event(self, event: TechEvent) -> None:
        """
        Upsert a TechEvent aggregate root along with its child entities
        (EventSourceEvidence and TimelineEntry) within an atomic transaction.
        """
        ...

    async def get_event(self, event_id: str) -> Optional[TechEvent]:
        """
        Load a complete TechEvent aggregate by its deterministic ID,
        including all associated sources and timeline entries.
        """
        ...

    async def get_active_events(self, limit: int = 100) -> List[TechEvent]:
        """
        Query non-stale TechEvent aggregates ordered by last_updated DESC.
        """
        ...

    async def get_events_since(
        self,
        cutoff_utc: datetime,
        limit: int = 5000,
    ) -> List[TechEvent]:
        """
        Fetch active TechEvent aggregates where last_updated >= cutoff_utc
        ordered by last_updated ASC for S07 clustering cold-start hydration.
        """
        ...

    async def get_events_by_entity(
        self,
        entity: str,
        limit: int = 50,
    ) -> List[TechEvent]:
        """
        Filter TechEvent aggregates that mention a specific entity.
        """
        ...

    async def delete_event(self, event_id: str) -> bool:
        """
        Delete a TechEvent by ID, cascading deletion to all child sources
        and timeline entries. Returns True if deleted, False if not found.
        """
        ...

    async def get_stats(self) -> Dict[str, Any]:
        """
        Return diagnostic store statistics (event counts, status breakdown, etc.).
        """
        ...


@runtime_checkable
class ArticleRepositoryProtocol(Protocol):
    """Asynchronous repository interface for NormalizedArticle entities."""

    async def save_article(self, article: NormalizedArticle) -> None:
        """
        Upsert a NormalizedArticle entity.
        """
        ...

    async def save_articles(self, articles: Sequence[NormalizedArticle]) -> int:
        """
        Batch upsert NormalizedArticle entities atomically. Returns count saved.
        """
        ...

    async def get_article(self, article_id: str) -> Optional[NormalizedArticle]:
        """
        Retrieve a NormalizedArticle by its hash ID.
        """
        ...

    async def get_article_by_canonical_url(
        self,
        canonical_url: str,
    ) -> Optional[NormalizedArticle]:
        """
        Retrieve a NormalizedArticle by its normalized canonical URL.
        """
        ...

    async def get_recent_articles(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
    ) -> List[NormalizedArticle]:
        """
        Retrieve recently discovered articles ordered by discovered_at DESC.
        """
        ...

    async def count_articles(self) -> int:
        """
        Return the total count of stored canonical articles.
        """
        ...

    async def search_articles(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[NormalizedArticle]:
        """
        Search articles by title, clean_text, summary, or tags matching the query.
        Returns matching NormalizedArticles ordered by discovered_at descending.
        """
        ...

    async def search_articles_fts(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        source_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[ArticleSearchResult]:
        """
        Execute ranked full-text search against canonical FTS5 index.
        Returns ranked ArticleSearchResult domain objects carrying BM25 score and snippet.
        """
        ...

    async def delete_article(self, article_id: str) -> bool:
        """
        Delete an article by ID. Returns True if deleted, False if not found.
        """
        ...

    async def delete_articles_older_than(
        self,
        cutoff: datetime,
    ) -> int:
        """
        Delete articles discovered prior to the specified timezone-aware cutoff datetime.
        Returns the number of deleted records.
        """
        ...


@runtime_checkable
class SourceHealthRepositoryProtocol(Protocol):
    """Asynchronous repository interface for SourceHealth resilience state."""

    async def save_health(self, health: SourceHealth) -> None:
        """
        Upsert the resilience state of a data source.
        """
        ...

    async def save_health_batch(self, health_records: Sequence[SourceHealth]) -> int:
        """
        Batch upsert multiple source health states atomically. Returns count saved.
        """
        ...

    async def get_health(self, source_id: str) -> Optional[SourceHealth]:
        """
        Retrieve the resilience state of a specific data source.
        """
        ...

    async def get_all_health(self) -> List[SourceHealth]:
        """
        Retrieve all recorded source health records.
        """
        ...

    async def get_health_by_status(self, status: SourceHealthStatus) -> List[SourceHealth]:
        """
        Retrieve all source health records with a matching health status.
        """
        ...

    async def delete_health(self, source_id: str) -> bool:
        """
        Delete a source health record by source_id. Returns True if deleted, False if not found.
        """
        ...


@runtime_checkable
class UserPreferencesRepositoryProtocol(Protocol):
    """Asynchronous repository interface for user personalization, topics, watchlist, and bookmarks."""

    async def save_preferences(self, preferences: Any) -> None:
        """
        Upsert a complete UserPreferences aggregate along with its topic subscriptions,
        company watchlist, and source preferences atomically.
        """
        ...

    async def get_preferences(self, user_id: str) -> Optional[Any]:
        """
        Load a complete UserPreferences aggregate by user_id. Returns None if not found.
        """
        ...

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
        ...

    async def get_user_bookmarks(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all bookmarked articles for a user ordered by created_at DESC.
        """
        ...

    async def remove_user_bookmark(self, user_id: str, article_id: str) -> bool:
        """
        Remove a bookmarked article for a user. Returns True if removed, False otherwise.
        """
        ...

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
        ...

    async def get_reading_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent reading history records for a user ordered by read_at DESC.
        """
        ...

    async def delete_user_data(self, user_id: str) -> Dict[str, int]:
        """
        Atomically delete all stored data (preferences, topics, watchlist, sources,
        bookmarks, reading history) for a given user. Returns per-table deletion counts.
        """
        ...
