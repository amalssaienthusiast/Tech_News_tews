"""
RejectedMetadataStore — SQLite Sink for Articles That Failed Quality/Freshness Checks.

Stores metadata of rejected articles so they can be used for deduplication
cross-referencing without re-processing. Auto-purges entries older than 7 days.

Table schema:
    rejected_articles (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT,
        source TEXT,
        rejection_reason TEXT,
        rejection_pipeline TEXT,  -- 'breaking' or 'standard'
        published_at TEXT,
        scraped_at TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

import logging
import sqlite3
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.types import Article

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("cache/rejected_articles.sqlite")
PURGE_DAYS = 7


class RejectedMetadataStore:
    """
    SQLite-backed store for rejected article metadata.

    Used for:
    1. Deduplication: prevents re-processing the same rejected article
    2. Analytics: track rejection reasons and patterns
    3. Debugging: inspect why articles were dropped
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._purge_old_entries()

    def _init_db(self) -> None:
        """Create the rejected_articles table if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rejected_articles (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    source TEXT,
                    rejection_reason TEXT,
                    rejection_pipeline TEXT,
                    published_at TEXT,
                    scraped_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rejected_url ON rejected_articles(url)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rejected_created ON rejected_articles(created_at)
            """)
            conn.commit()
        logger.info(f"RejectedMetadataStore initialized at {self._db_path}")

    def store(
        self,
        article: Article,
        rejection_reason: str,
        rejection_pipeline: str = "unknown",
    ) -> bool:
        """
        Store rejected article metadata.

        Args:
            article: The rejected Article object
            rejection_reason: Why it was rejected (e.g., 'stale_45min', 'no_thumbnail', 'spam')
            rejection_pipeline: Which pipeline rejected it ('breaking' or 'standard')

        Returns:
            True if stored successfully, False if already exists or error
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO rejected_articles
                       (id, url, title, source, rejection_reason, rejection_pipeline, published_at, scraped_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        article.id,
                        article.url,
                        article.title,
                        article.source,
                        rejection_reason,
                        rejection_pipeline,
                        article.published_at.isoformat() if article.published_at else None,
                        article.scraped_at.isoformat() if article.scraped_at else None,
                    ),
                )
                conn.commit()
                return conn.total_changes > 0
        except Exception as e:
            logger.error(f"Error storing rejected article metadata: {e}")
            return False

    def is_known_rejected(self, article_id: str) -> bool:
        """Check if an article ID has been previously rejected."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM rejected_articles WHERE id = ? LIMIT 1",
                    (article_id,),
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking rejected article: {e}")
            return False

    def is_url_known_rejected(self, url: str) -> bool:
        """Check if a URL has been previously rejected."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM rejected_articles WHERE url = ? LIMIT 1",
                    (url,),
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking rejected URL: {e}")
            return False

    def _purge_old_entries(self) -> int:
        """Remove entries older than PURGE_DAYS. Returns count of purged rows."""
        cutoff = (datetime.now(UTC) - timedelta(days=PURGE_DAYS)).isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM rejected_articles WHERE created_at < ?",
                    (cutoff,),
                )
                conn.commit()
                purged = cursor.rowcount
                if purged > 0:
                    logger.info(f"RejectedMetadataStore purged {purged} entries older than {PURGE_DAYS} days")
                return purged
        except Exception as e:
            logger.error(f"Error purging old rejected entries: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the rejected metadata store."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM rejected_articles").fetchone()[0]

                # Breakdown by rejection reason
                reasons = {}
                for row in conn.execute(
                    "SELECT rejection_reason, COUNT(*) FROM rejected_articles GROUP BY rejection_reason ORDER BY COUNT(*) DESC LIMIT 10"
                ):
                    reasons[row[0] or "unknown"] = row[1]

                # Breakdown by pipeline
                pipelines = {}
                for row in conn.execute(
                    "SELECT rejection_pipeline, COUNT(*) FROM rejected_articles GROUP BY rejection_pipeline"
                ):
                    pipelines[row[0] or "unknown"] = row[1]

                return {
                    "total_rejected": total,
                    "by_reason": reasons,
                    "by_pipeline": pipelines,
                    "db_path": str(self._db_path),
                }
        except Exception as e:
            logger.error(f"Error getting rejected store stats: {e}")
            return {"total_rejected": 0, "error": str(e)}
