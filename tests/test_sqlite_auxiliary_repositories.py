"""
Tests for Subphase 5F-B Auxiliary SQLite Repositories.
Location: tests/test_sqlite_auxiliary_repositories.py

Validates:
1. ArticleRepositoryProtocol: search_articles and delete_articles_older_than.
2. UserPreferencesRepositoryProtocol: SqliteUserPreferencesRepository CRUD,
   topics/watchlist/sources sync, bookmarks, reading history, and GDPR atomic deletion.
3. Cold-restart resilience, multi-user isolation, and timezone safety.
4. Strict architectural isolation (zero legacy storage imports).
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import List

import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.validators import DomainValidationError
from src.domain.models import NormalizedArticle
from src.storage.protocols import (
    ArticleRepositoryProtocol,
    UserPreferencesRepositoryProtocol,
)
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_user_preferences_repository import SqliteUserPreferencesRepository
from src.user.preferences import (
    AlertThresholds,
    CompanyWatchItem,
    DeliveryFrequency,
    DeliverySettings,
    SourcePreference,
    TopicSubscription,
    UserPreferences,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated SQLite database path per test."""
    return tmp_path / "test_auxiliary.db"


@pytest.fixture
async def sqlite_engine(temp_db_path: Path) -> SqliteEngine:
    """Instantiate and initialize a clean SqliteEngine."""
    engine = SqliteEngine(db_path=temp_db_path)
    await engine.initialize_schema()
    try:
        yield engine
    finally:
        await engine.aclose()


@pytest.fixture
def article_repo(sqlite_engine: SqliteEngine) -> SqliteArticleRepository:
    return SqliteArticleRepository(engine=sqlite_engine)


@pytest.fixture
def user_repo(sqlite_engine: SqliteEngine) -> SqliteUserPreferencesRepository:
    return SqliteUserPreferencesRepository(engine=sqlite_engine)


def _make_article(
    article_id: str,
    title: str,
    text: str = "",
    summary: str = "",
    tags: tuple = (),
    discovered_at: datetime = None,
) -> NormalizedArticle:
    disc = discovered_at or datetime.now(UTC)
    return NormalizedArticle(
        id=article_id,
        canonical_url=f"https://example.com/articles/{article_id}",
        original_url=f"https://example.com/articles/{article_id}",
        title=title,
        clean_text=text,
        summary=summary,
        source_id="techcrunch",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        discovered_at=disc,
        published_at=disc,
        language="en",
        image_url=None,
        authors=("Alice Smith",),
        tags=tags,
        metadata={},
    )


# =============================================================================
# 1. ARTICLE SEARCH TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_article_search_by_title_and_summary(article_repo: SqliteArticleRepository) -> None:
    """Verify article search matches title, summary, and clean text."""
    art1 = _make_article("art_quantum", "Quantum Computing Breakthrough", summary="New qubit fidelity record")
    art2 = _make_article("art_ai", "Deep Learning Transformers", summary="LLM architecture analysis")
    art3 = _make_article("art_fusion", "Nuclear Fusion Progress", text="Clean energy breakthrough announced")

    await article_repo.save_articles([art1, art2, art3])

    # Search title
    results_quantum = await article_repo.search_articles("Quantum")
    assert len(results_quantum) == 1
    assert results_quantum[0].id == "art_quantum"

    # Search summary
    results_llm = await article_repo.search_articles("architecture")
    assert len(results_llm) == 1
    assert results_llm[0].id == "art_ai"

    # Search clean_text
    results_fusion = await article_repo.search_articles("energy breakthrough")
    assert len(results_fusion) == 1
    assert results_fusion[0].id == "art_fusion"


@pytest.mark.asyncio
async def test_article_search_by_tags(article_repo: SqliteArticleRepository) -> None:
    """Verify article search matches tags array."""
    art1 = _make_article("art_sec", "Zero Day Vulnerability Discovered", tags=("cybersecurity", "cve", "infosec"))
    art2 = _make_article("art_cloud", "AWS Announces New Graviton Instances", tags=("cloud", "hardware", "aws"))

    await article_repo.save_articles([art1, art2])

    results = await article_repo.search_articles("cybersecurity")
    assert len(results) == 1
    assert results[0].id == "art_sec"


@pytest.mark.asyncio
async def test_article_search_pagination_and_ordering(article_repo: SqliteArticleRepository) -> None:
    """Verify search pagination and ordering by discovered_at DESC."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    articles = [
        _make_article(f"art_{i:02d}", f"Rust Systems Update {i}", discovered_at=base_time + timedelta(hours=i))
        for i in range(10)
    ]
    await article_repo.save_articles(articles)

    # Page 1
    page1 = await article_repo.search_articles("Rust", limit=4, offset=0)
    assert len(page1) == 4
    assert page1[0].id == "art_09"
    assert page1[1].id == "art_08"
    assert page1[2].id == "art_07"
    assert page1[3].id == "art_06"

    # Page 2
    page2 = await article_repo.search_articles("Rust", limit=4, offset=4)
    assert len(page2) == 4
    assert page2[0].id == "art_05"
    assert page2[1].id == "art_04"


@pytest.mark.asyncio
async def test_article_search_empty_and_sql_injection_safety(article_repo: SqliteArticleRepository) -> None:
    """Verify empty query returns empty list and SQL injection payload is treated safely."""
    art1 = _make_article("art_sec", "Security Update")
    await article_repo.save_article(art1)

    # Empty queries
    assert await article_repo.search_articles("") == []
    assert await article_repo.search_articles("   ") == []

    # SQL Injection attempt
    injection_query = "' OR '1'='1' --"
    results = await article_repo.search_articles(injection_query)
    assert len(results) == 0


# =============================================================================
# 2. ARTICLE RETENTION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_article_retention_delete_older_than(article_repo: SqliteArticleRepository) -> None:
    """Verify delete_articles_older_than purges old articles and preserves recent articles."""
    now = datetime.now(UTC)
    old1 = _make_article("art_old1", "Old Article 1", discovered_at=now - timedelta(days=45))
    old2 = _make_article("art_old2", "Old Article 2", discovered_at=now - timedelta(days=35))
    recent1 = _make_article("art_rec1", "Recent Article 1", discovered_at=now - timedelta(days=10))
    recent2 = _make_article("art_rec2", "Recent Article 2", discovered_at=now - timedelta(hours=2))

    await article_repo.save_articles([old1, old2, recent1, recent2])
    assert await article_repo.count_articles() == 4

    cutoff = now - timedelta(days=30)
    deleted_count = await article_repo.delete_articles_older_than(cutoff)
    assert deleted_count == 2

    assert await article_repo.count_articles() == 2
    assert await article_repo.get_article("art_old1") is None
    assert await article_repo.get_article("art_old2") is None
    assert await article_repo.get_article("art_rec1") is not None
    assert await article_repo.get_article("art_rec2") is not None


@pytest.mark.asyncio
async def test_article_retention_naive_datetime_rejection(article_repo: SqliteArticleRepository) -> None:
    """Verify naive datetimes are rejected during retention pruning."""
    naive_cutoff = datetime(2026, 1, 1, 0, 0, 0)
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        await article_repo.delete_articles_older_than(naive_cutoff)


# =============================================================================
# 3. USER PREFERENCES REPOSITORY TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_user_preferences_save_and_get_roundtrip(user_repo: SqliteUserPreferencesRepository) -> None:
    """Verify full save and retrieval of UserPreferences domain aggregate."""
    now = datetime.now(UTC)
    prefs = UserPreferences(
        user_id="usr_12345",
        display_name="Amal Tech",
        theme="tokyo_night",
        articles_per_page=30,
        reading_history_enabled=True,
        topics=[
            TopicSubscription(topic="AI & Machine Learning", weight=1.5, keywords=["llm", "transformers"], enabled=True),
            TopicSubscription(topic="Cybersecurity", weight=0.8, keywords=["zero-day"], enabled=False),
        ],
        watchlist=[
            CompanyWatchItem(name="NVIDIA", ticker="NVDA", aliases=["Nvidia Corp"], priority=1, enabled=True),
            CompanyWatchItem(name="Google", ticker="GOOGL", aliases=["Alphabet"], priority=2, enabled=True),
        ],
        sources=[
            SourcePreference(source_domain="techcrunch.com", source_name="TechCrunch", preferred=True, trust_score=0.9),
            SourcePreference(source_domain="spamnews.io", source_name="Spam News", blocked=True, trust_score=0.1),
        ],
        delivery=DeliverySettings(
            email_enabled=True,
            email_address="user@example.com",
            email_frequency=DeliveryFrequency.DAILY,
            desktop_notifications=True,
            telegram_enabled=True,
            telegram_chat_id="12345678",
        ),
        alerts=AlertThresholds(
            min_criticality=8,
            min_sentiment_change=0.4,
            watched_company_threshold=4,
            max_alerts_per_hour=5,
            quiet_hours_enabled=True,
            quiet_hours_start="23:00",
            quiet_hours_end="06:00",
        ),
        created_at=now - timedelta(days=1),
        updated_at=now,
    )

    await user_repo.save_preferences(prefs)

    loaded = await user_repo.get_preferences("usr_12345")
    assert loaded is not None
    assert loaded.user_id == "usr_12345"
    assert loaded.display_name == "Amal Tech"
    assert loaded.theme == "tokyo_night"
    assert loaded.articles_per_page == 30
    assert loaded.reading_history_enabled is True

    # Topics
    assert len(loaded.topics) == 2
    assert loaded.topics[0].topic == "AI & Machine Learning"
    assert loaded.topics[0].weight == 1.5
    assert loaded.topics[0].keywords == ["llm", "transformers"]
    assert loaded.topics[0].enabled is True
    assert loaded.topics[1].topic == "Cybersecurity"
    assert loaded.topics[1].enabled is False

    # Watchlist
    assert len(loaded.watchlist) == 2
    assert loaded.watchlist[0].name == "NVIDIA"
    assert loaded.watchlist[0].ticker == "NVDA"
    assert loaded.watchlist[0].aliases == ["Nvidia Corp"]

    # Sources
    assert len(loaded.sources) == 2
    assert loaded.sources[0].source_domain == "techcrunch.com"
    assert loaded.sources[0].preferred is True
    assert loaded.sources[1].source_domain == "spamnews.io"
    assert loaded.sources[1].blocked is True

    # Delivery & Alerts
    assert loaded.delivery.email_enabled is True
    assert loaded.delivery.email_address == "user@example.com"
    assert loaded.delivery.telegram_enabled is True
    assert loaded.alerts.min_criticality == 8
    assert loaded.alerts.quiet_hours_enabled is True


@pytest.mark.asyncio
async def test_user_preferences_update_existing(user_repo: SqliteUserPreferencesRepository) -> None:
    """Verify updating preferences replaces child collections cleanly without duplicate rows."""
    prefs_v1 = UserPreferences(
        user_id="usr_update",
        display_name="User V1",
        topics=[TopicSubscription(topic="AI", weight=1.0)],
        watchlist=[CompanyWatchItem(name="Apple", ticker="AAPL")],
    )
    await user_repo.save_preferences(prefs_v1)

    prefs_v2 = UserPreferences(
        user_id="usr_update",
        display_name="User V2 Updated",
        topics=[
            TopicSubscription(topic="Quantum", weight=1.8),
            TopicSubscription(topic="Robotics", weight=1.2),
        ],
        watchlist=[CompanyWatchItem(name="Microsoft", ticker="MSFT")],
    )
    await user_repo.save_preferences(prefs_v2)

    loaded = await user_repo.get_preferences("usr_update")
    assert loaded is not None
    assert loaded.display_name == "User V2 Updated"
    assert len(loaded.topics) == 2
    assert [t.topic for t in loaded.topics] == ["Quantum", "Robotics"]
    assert len(loaded.watchlist) == 1
    assert loaded.watchlist[0].name == "Microsoft"


@pytest.mark.asyncio
async def test_user_preferences_nonexistent(user_repo: SqliteUserPreferencesRepository) -> None:
    """Verify get_preferences returns None for non-existent user."""
    assert await user_repo.get_preferences("usr_missing_999") is None


@pytest.mark.asyncio
async def test_user_preferences_cold_restart_persistence(temp_db_path: Path) -> None:
    """Verify UserPreferences persist across clean cold-engine restart."""
    # Context 1: Save
    engine1 = SqliteEngine(db_path=temp_db_path)
    repo1 = SqliteUserPreferencesRepository(engine=engine1)
    prefs = UserPreferences(
        user_id="usr_restart",
        display_name="Restart User",
        topics=[TopicSubscription(topic="Space Tech", weight=1.4)],
    )
    await repo1.save_preferences(prefs)
    await engine1.aclose()

    # Context 2: Reopen cold
    engine2 = SqliteEngine(db_path=temp_db_path)
    repo2 = SqliteUserPreferencesRepository(engine=engine2)
    loaded = await repo2.get_preferences("usr_restart")
    assert loaded is not None
    assert loaded.display_name == "Restart User"
    assert loaded.topics[0].topic == "Space Tech"
    await engine2.aclose()


@pytest.mark.asyncio
async def test_user_bookmarks_and_reading_history(user_repo: SqliteUserPreferencesRepository) -> None:
    """Verify bookmarking articles and recording reading history."""
    prefs = UserPreferences(user_id="usr_bookmarker", display_name="Bookmarker")
    await user_repo.save_preferences(prefs)

    # 1. Add bookmarks
    await user_repo.add_user_bookmark(
        user_id="usr_bookmarker",
        article_id="art_101",
        title="Superconducting Qubits Explained",
        url="https://example.com/101",
        source="Nature",
        notes="Read before conference",
    )
    await user_repo.add_user_bookmark(
        user_id="usr_bookmarker",
        article_id="art_102",
        title="Silicon Photonics Breakthrough",
        url="https://example.com/102",
        source="Arxiv",
    )

    bookmarks = await user_repo.get_user_bookmarks("usr_bookmarker")
    assert len(bookmarks) == 2
    assert bookmarks[0]["article_id"] in ("art_101", "art_102")

    # Remove one bookmark
    removed = await user_repo.remove_user_bookmark("usr_bookmarker", "art_101")
    assert removed is True
    remaining = await user_repo.get_user_bookmarks("usr_bookmarker")
    assert len(remaining) == 1
    assert remaining[0]["article_id"] == "art_102"

    # 2. Reading history
    await user_repo.add_reading_history("usr_bookmarker", "art_201", time_spent_seconds=120, clicked_links=3)
    await user_repo.add_reading_history("usr_bookmarker", "art_202", time_spent_seconds=45, clicked_links=1)

    history = await user_repo.get_reading_history("usr_bookmarker")
    assert len(history) == 2
    assert history[0]["article_id"] == "art_202"
    assert history[1]["article_id"] == "art_201"


@pytest.mark.asyncio
async def test_user_data_gdpr_atomic_deletion(user_repo: SqliteUserPreferencesRepository) -> None:
    """Verify delete_user_data completely deletes user A's data while leaving user B intact."""
    # User A
    prefs_a = UserPreferences(
        user_id="usr_alice",
        display_name="Alice",
        topics=[TopicSubscription(topic="AI", weight=1.0)],
        watchlist=[CompanyWatchItem(name="OpenAI", ticker=None)],
        sources=[SourcePreference(source_domain="theverge.com")],
    )
    await user_repo.save_preferences(prefs_a)
    await user_repo.add_user_bookmark("usr_alice", "art_a1", "Alice Bookmark", "https://example.com/a1")
    await user_repo.add_reading_history("usr_alice", "art_a1", time_spent_seconds=30)

    # User B
    prefs_b = UserPreferences(
        user_id="usr_bob",
        display_name="Bob",
        topics=[TopicSubscription(topic="FinTech", weight=1.0)],
    )
    await user_repo.save_preferences(prefs_b)
    await user_repo.add_user_bookmark("usr_bob", "art_b1", "Bob Bookmark", "https://example.com/b1")

    # Purge User A
    counts = await user_repo.delete_user_data("usr_alice")
    assert counts["user_preferences"] == 1
    assert counts["user_topics"] == 1
    assert counts["user_watchlist"] == 1
    assert counts["user_sources"] == 1
    assert counts["user_bookmarks"] == 1
    assert counts["user_reading_history"] == 1

    # Verify User A is completely gone
    assert await user_repo.get_preferences("usr_alice") is None
    assert await user_repo.get_user_bookmarks("usr_alice") == []
    assert await user_repo.get_reading_history("usr_alice") == []

    # Verify User B is completely untouched
    loaded_b = await user_repo.get_preferences("usr_bob")
    assert loaded_b is not None
    assert loaded_b.display_name == "Bob"
    assert len(await user_repo.get_user_bookmarks("usr_bob")) == 1


# =============================================================================
# 4. PROTOCOL CONFORMANCE & AST ISOLATION TESTS
# =============================================================================

def test_auxiliary_protocol_conformance() -> None:
    """Verify repository classes satisfy their respective Protocol definitions."""
    assert issubclass(SqliteArticleRepository, ArticleRepositoryProtocol)
    assert issubclass(SqliteUserPreferencesRepository, UserPreferencesRepositoryProtocol)


def test_ast_layer_boundaries_zero_legacy_imports() -> None:
    """Verify storage repository implementations have 0 imports of legacy storage modules."""
    files_to_check = [
        Path("src/storage/sqlite_article_repository.py"),
        Path("src/storage/sqlite_user_preferences_repository.py"),
        Path("src/storage/protocols.py"),
    ]

    forbidden_modules = {
        "src.database",
        "src.db_storage",
        "src.events",
        "database",
        "db_storage",
        "events",
    }

    for file_path in files_to_check:
        assert file_path.exists(), f"File {file_path} must exist"
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_modules:
                        assert not alias.name.startswith(forbidden), (
                            f"Forbidden import '{alias.name}' found in {file_path} at line {node.lineno}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_modules:
                        assert not node.module.startswith(forbidden), (
                            f"Forbidden from-import '{node.module}' found in {file_path} at line {node.lineno}"
                        )
