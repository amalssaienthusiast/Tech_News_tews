"""
Canonical Storage Package (Phase 5).
Location: src/storage/__init__.py
"""

from .protocols import (
    ArticleRepositoryProtocol,
    EventRepositoryProtocol,
    SourceHealthRepositoryProtocol,
    UserPreferencesRepositoryProtocol,
)
from .sqlite_engine import (
    DEFAULT_CANONICAL_DB_PATH,
    SCHEMA_SQL_PATH,
    SqliteEngine,
)
from .sqlite_article_repository import SqliteArticleRepository
from .sqlite_event_repository import SqliteEventRepository
from .sqlite_source_health_repository import SqliteSourceHealthRepository
from .sqlite_user_preferences_repository import SqliteUserPreferencesRepository

__all__ = [
    "ArticleRepositoryProtocol",
    "EventRepositoryProtocol",
    "SourceHealthRepositoryProtocol",
    "UserPreferencesRepositoryProtocol",
    "SqliteEngine",
    "SqliteArticleRepository",
    "SqliteEventRepository",
    "SqliteSourceHealthRepository",
    "SqliteUserPreferencesRepository",
    "DEFAULT_CANONICAL_DB_PATH",
    "SCHEMA_SQL_PATH",
]
