"""
SQLite-backed Canonical Article Repository.
Location: src/storage/sqlite_article_repository.py

Implements ArticleRepositoryProtocol for NormalizedArticle entities:
- Asynchronous persistence using SqliteEngine
- Strict domain round-trip mapping (enums, UTC datetimes, tuples, JSON metadata)
- Deterministic idempotent upsert on sha256(canonical_url)[:16] ID
- Atomic batch operations and bounded pagination
- Preserves unique constraints on canonical_url
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import aiosqlite

from ..domain.enums import SourceTier, ZombieSpecies
from ..domain.models import ArticleSearchResult, NormalizedArticle
from ..domain.validators import DomainValidationError, validate_utc_datetime
from .fts_sanitizer import sanitize_fts5_query
from .protocols import ArticleRepositoryProtocol
from .sqlite_engine import SqliteEngine

logger = logging.getLogger(__name__)


def _normalize_datetime(dt: Optional[datetime], field_name: str) -> Optional[datetime]:
    """Validate timezone awareness and normalize to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise DomainValidationError(f"Datetime field '{field_name}' must be timezone-aware (naive given: {dt})")
    return dt.astimezone(UTC)


def _parse_source_tier(val: Any) -> SourceTier:
    """Parse source tier safely whether stored as integer or string."""
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


def _parse_zombie_species(val: Any) -> ZombieSpecies:
    """Parse zombie species safely from stored string."""
    if isinstance(val, ZombieSpecies):
        return val
    if isinstance(val, str):
        try:
            return ZombieSpecies(val.strip().lower())
        except ValueError:
            pass
    return ZombieSpecies.RSS


class SqliteArticleRepository(ArticleRepositoryProtocol):
    """
    SQLite-backed asynchronous repository for NormalizedArticle entities.
    """

    def __init__(self, engine: Optional[SqliteEngine] = None, auto_init: bool = True) -> None:
        self.engine = engine or SqliteEngine()
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

    def _article_to_params(self, article: NormalizedArticle) -> Dict[str, Any]:
        """Convert a NormalizedArticle domain object into parameterized SQL values."""
        disc_at = _normalize_datetime(article.discovered_at, "discovered_at")
        pub_at = _normalize_datetime(article.published_at, "published_at")

        # Source tier representation
        tier_val = article.source_tier.value if isinstance(article.source_tier, SourceTier) else int(article.source_tier)
        species_val = article.zombie_species.value if isinstance(article.zombie_species, ZombieSpecies) else str(article.zombie_species)

        return {
            "id": article.id,
            "canonical_url": article.canonical_url,
            "original_url": article.original_url,
            "title": article.title,
            "clean_text": article.clean_text or "",
            "summary": article.summary or "",
            "source_id": article.source_id,
            "source_name": article.source_name,
            "source_tier": tier_val,
            "zombie_species": species_val,
            "discovered_at": disc_at.isoformat(),
            "published_at": pub_at.isoformat() if pub_at else None,
            "language": article.language or "en",
            "image_url": article.image_url,
            "authors": json.dumps(list(article.authors or [])),
            "tags": json.dumps(list(article.tags or [])),
            "metadata": json.dumps(dict(article.metadata or {})),
        }

    def _row_to_article(self, row: aiosqlite.Row) -> NormalizedArticle:
        """Reconstruct a NormalizedArticle domain model from an aiosqlite Row."""
        discovered_at = datetime.fromisoformat(row["discovered_at"]).astimezone(UTC)
        published_at = (
            datetime.fromisoformat(row["published_at"]).astimezone(UTC)
            if row["published_at"]
            else None
        )

        authors = tuple(json.loads(row["authors"])) if row["authors"] else ()
        tags = tuple(json.loads(row["tags"])) if row["tags"] else ()
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        return NormalizedArticle(
            id=row["id"],
            canonical_url=row["canonical_url"],
            original_url=row["original_url"],
            title=row["title"],
            clean_text=row["clean_text"] or "",
            summary=row["summary"] or "",
            source_id=row["source_id"],
            source_name=row["source_name"],
            source_tier=_parse_source_tier(row["source_tier"]),
            zombie_species=_parse_zombie_species(row["zombie_species"]),
            discovered_at=discovered_at,
            published_at=published_at,
            language=row["language"] or "en",
            image_url=row["image_url"],
            authors=authors,
            tags=tags,
            metadata=metadata,
        )

    async def save_article(self, article: NormalizedArticle) -> None:
        """
        Upsert a NormalizedArticle entity atomically.
        """
        if not isinstance(article, NormalizedArticle):
            raise DomainValidationError(f"Expected NormalizedArticle instance, got {type(article)}")

        await self._ensure_initialized()
        params = self._article_to_params(article)

        upsert_sql = """
        INSERT INTO canonical_articles (
            id, canonical_url, original_url, title, clean_text, summary,
            source_id, source_name, source_tier, zombie_species,
            discovered_at, published_at, language, image_url,
            authors, tags, metadata
        ) VALUES (
            :id, :canonical_url, :original_url, :title, :clean_text, :summary,
            :source_id, :source_name, :source_tier, :zombie_species,
            :discovered_at, :published_at, :language, :image_url,
            :authors, :tags, :metadata
        )
        ON CONFLICT(id) DO UPDATE SET
            canonical_url = excluded.canonical_url,
            original_url = excluded.original_url,
            title = excluded.title,
            clean_text = excluded.clean_text,
            summary = excluded.summary,
            source_id = excluded.source_id,
            source_name = excluded.source_name,
            source_tier = excluded.source_tier,
            zombie_species = excluded.zombie_species,
            discovered_at = excluded.discovered_at,
            published_at = excluded.published_at,
            language = excluded.language,
            image_url = excluded.image_url,
            authors = excluded.authors,
            tags = excluded.tags,
            metadata = excluded.metadata;
        """
        await self.engine.execute(upsert_sql, params)

    async def save_articles(self, articles: Sequence[NormalizedArticle]) -> int:
        """
        Batch upsert multiple NormalizedArticle entities atomically within a single transaction.
        """
        if not articles:
            return 0

        await self._ensure_initialized()

        upsert_sql = """
        INSERT INTO canonical_articles (
            id, canonical_url, original_url, title, clean_text, summary,
            source_id, source_name, source_tier, zombie_species,
            discovered_at, published_at, language, image_url,
            authors, tags, metadata
        ) VALUES (
            :id, :canonical_url, :original_url, :title, :clean_text, :summary,
            :source_id, :source_name, :source_tier, :zombie_species,
            :discovered_at, :published_at, :language, :image_url,
            :authors, :tags, :metadata
        )
        ON CONFLICT(id) DO UPDATE SET
            canonical_url = excluded.canonical_url,
            original_url = excluded.original_url,
            title = excluded.title,
            clean_text = excluded.clean_text,
            summary = excluded.summary,
            source_id = excluded.source_id,
            source_name = excluded.source_name,
            source_tier = excluded.source_tier,
            zombie_species = excluded.zombie_species,
            discovered_at = excluded.discovered_at,
            published_at = excluded.published_at,
            language = excluded.language,
            image_url = excluded.image_url,
            authors = excluded.authors,
            tags = excluded.tags,
            metadata = excluded.metadata;
        """

        param_list = [self._article_to_params(a) for a in articles]

        async with self.engine.transaction() as conn:
            await conn.executemany(upsert_sql, param_list)

        return len(articles)

    async def get_article(self, article_id: str) -> Optional[NormalizedArticle]:
        """
        Retrieve a NormalizedArticle by its hash ID.
        """
        await self._ensure_initialized()
        sql = "SELECT * FROM canonical_articles WHERE id = ?;"
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, (article_id,))
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_article(row)

    async def get_article_by_canonical_url(self, canonical_url: str) -> Optional[NormalizedArticle]:
        """
        Retrieve a NormalizedArticle by its canonical URL.
        """
        await self._ensure_initialized()
        sql = "SELECT * FROM canonical_articles WHERE canonical_url = ?;"
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, (canonical_url.strip(),))
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_article(row)

    async def get_recent_articles(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
    ) -> List[NormalizedArticle]:
        """
        Retrieve recent articles ordered by discovered_at DESC.
        """
        await self._ensure_initialized()
        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)

        if source_id:
            sql = """
            SELECT * FROM canonical_articles
            WHERE source_id = ?
            ORDER BY discovered_at DESC
            LIMIT ? OFFSET ?;
            """
            params: Tuple[Any, ...] = (source_id.strip(), safe_limit, safe_offset)
        else:
            sql = """
            SELECT * FROM canonical_articles
            ORDER BY discovered_at DESC
            LIMIT ? OFFSET ?;
            """
            params = (safe_limit, safe_offset)

        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            return [self._row_to_article(r) for r in rows]

    async def count_articles(self) -> int:
        """
        Return the total count of stored canonical articles.
        """
        await self._ensure_initialized()
        sql = "SELECT COUNT(*) FROM canonical_articles;"
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql)
            (total_count,) = await cursor.fetchone()
            return int(total_count)

    async def delete_article(self, article_id: str) -> bool:
        """
        Delete an article by ID. Returns True if deleted, False if not found.
        """
        await self._ensure_initialized()
        sql = "DELETE FROM canonical_articles WHERE id = ?;"
        async with self.engine.transaction() as conn:
            cursor = await conn.execute(sql, (article_id,))
            return cursor.rowcount > 0

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
        await self._ensure_initialized()
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)
        pattern = f"%{cleaned_query}%"

        sql = """
        SELECT * FROM canonical_articles
        WHERE title LIKE ? OR clean_text LIKE ? OR summary LIKE ? OR tags LIKE ?
        ORDER BY discovered_at DESC
        LIMIT ? OFFSET ?;
        """
        async with self.engine.connect() as conn:
            cursor = await conn.execute(
                sql,
                (pattern, pattern, pattern, pattern, safe_limit, safe_offset),
            )
            rows = await cursor.fetchall()
            return [self._row_to_article(r) for r in rows]

    async def delete_articles_older_than(
        self,
        cutoff: datetime,
    ) -> int:
        """
        Delete articles discovered prior to the specified timezone-aware cutoff datetime.
        Returns the number of deleted records.
        """
        await self._ensure_initialized()
        cutoff_utc = _normalize_datetime(cutoff, "cutoff")

        sql = "DELETE FROM canonical_articles WHERE discovered_at < ?;"
        async with self.engine.transaction() as conn:
            cursor = await conn.execute(sql, (cutoff_utc.isoformat(),))
            return int(cursor.rowcount)

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
        Applies BM25 relevance scoring and contextual match snippets.
        """
        await self._ensure_initialized()
        sanitized = sanitize_fts5_query(query)
        if not sanitized:
            return []

        safe_limit = max(1, min(limit, 500))
        safe_offset = max(0, offset)

        conditions: List[str] = ["canonical_articles_fts MATCH ?"]
        params: List[Any] = [sanitized]

        if source_id:
            conditions.append("a.source_id = ?")
            params.append(source_id)

        if tag:
            conditions.append("a.tags LIKE ?")
            params.append(f"%{tag}%")

        where_clause = " AND ".join(conditions)

        # FTS5 column weights matching table schema: (id: 0.0, title: 5.0, clean_text: 1.0, summary: 2.0, tags: 3.0)
        # Note: In SQLite FTS5 bm25(), lower/negative scores indicate higher relevance.
        sql = f"""
        SELECT 
            a.*,
            bm25(canonical_articles_fts, 0.0, 5.0, 1.0, 2.0, 3.0) AS rank,
            COALESCE(
                NULLIF(snippet(canonical_articles_fts, 1, '<mark>', '</mark>', '...', 20), ''),
                NULLIF(snippet(canonical_articles_fts, 3, '<mark>', '</mark>', '...', 24), ''),
                NULLIF(snippet(canonical_articles_fts, 2, '<mark>', '</mark>', '...', 32), ''),
                a.summary,
                ''
            ) AS match_snippet
        FROM canonical_articles_fts
        JOIN canonical_articles a ON a.id = canonical_articles_fts.id
        WHERE {where_clause}
        ORDER BY rank ASC
        LIMIT ? OFFSET ?;
        """
        params.extend([safe_limit, safe_offset])

        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            results: List[ArticleSearchResult] = []
            for r in rows:
                article = self._row_to_article(r)
                raw_rank = float(r["rank"])
                relevance = abs(raw_rank)
                snippet_text = str(r["match_snippet"]) if r["match_snippet"] else ""
                results.append(ArticleSearchResult(
                    article=article,
                    relevance_score=relevance,
                    snippet=snippet_text,
                ))
            return results
