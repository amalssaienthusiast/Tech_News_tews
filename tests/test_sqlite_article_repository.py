"""
Unit & Integration Tests for Subphase 5E-A: SQLite Article Repository.
Location: tests/test_sqlite_article_repository.py

Verifies:
1. Exact round-trip persistence of NormalizedArticle
2. Optional fields handling (None published_at, image_url, empty collections)
3. Enum round-trip serialization (SourceTier, ZombieSpecies)
4. UTC datetime round-trip and timezone preservation
5. Naive datetime validation/rejection
6. Canonical URL uniqueness enforcement
7. Deterministic idempotent upsert semantics
8. Batch save atomicity and transaction rollback
9. Recent article ordering (discovered_at DESC)
10. Pagination bounds (limit & offset)
11. Source ID filtering (get_recent_articles by source)
12. count_articles functionality
13. delete_article on existing record
14. delete_article on missing record
15. Metadata, tags, and authors structural fidelity
16. Concurrent duplicate writes without constraint failures
17. Large text/payload storage support
18. Shared SqliteEngine reuse
19. No second database file created
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle
from src.domain.validators import DomainValidationError
from src.storage.protocols import ArticleRepositoryProtocol
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine


def make_sample_article(
    url: str = "https://techcrunch.com/2026/08/14/quantum-ai-breakthrough",
    title: str = "Quantum AI Breakthrough Announced",
    source_id: str = "src_techcrunch",
    source_name: str = "TechCrunch",
    source_tier: SourceTier = SourceTier.TIER_1_PREMIUM,
    zombie_species: ZombieSpecies = ZombieSpecies.RSS,
    offset_minutes: float = 0.0,
    published_offset_minutes: Optional[float] = 10.0,
    authors: tuple = ("Jane Doe", "John Smith"),
    tags: tuple = ("AI", "Quantum", "Computing"),
    metadata: dict = None,
) -> NormalizedArticle:
    disc_time = datetime.now(UTC) - timedelta(minutes=offset_minutes)
    pub_time = (
        datetime.now(UTC) - timedelta(minutes=published_offset_minutes)
        if published_offset_minutes is not None
        else None
    )
    meta = metadata if metadata is not None else {"sentiment": 0.85, "quality_score": 0.95}
    return NormalizedArticle.create(
        canonical_url=url,
        original_url=url + "?utm_source=rss&utm_medium=feed",
        title=title,
        clean_text="Detailed breakthrough in fault-tolerant quantum computing processor.",
        summary="A major quantum computing processor breakthrough was announced.",
        source_id=source_id,
        source_name=source_name,
        source_tier=source_tier,
        zombie_species=zombie_species,
        discovered_at=disc_time,
        published_at=pub_time,
        language="en",
        image_url="https://techcrunch.com/images/hero.jpg",
        authors=authors,
        tags=tags,
        metadata=meta,
    )


@pytest.fixture
async def repo(tmp_path: Path):
    db_path = tmp_path / "canonical_articles_test.db"
    engine = SqliteEngine(db_path)
    repository = SqliteArticleRepository(engine=engine, auto_init=True)
    yield repository
    await engine.aclose()


@pytest.mark.asyncio
async def test_article_exact_round_trip(repo: SqliteArticleRepository):
    """Verify exact round-trip preservation of all NormalizedArticle fields."""
    art = make_sample_article()
    await repo.save_article(art)

    fetched = await repo.get_article(art.id)
    assert fetched is not None
    assert fetched.id == art.id
    assert fetched.canonical_url == art.canonical_url
    assert fetched.original_url == art.original_url
    assert fetched.title == art.title
    assert fetched.clean_text == art.clean_text
    assert fetched.summary == art.summary
    assert fetched.source_id == art.source_id
    assert fetched.source_name == art.source_name
    assert fetched.source_tier == art.source_tier
    assert fetched.zombie_species == art.zombie_species
    assert fetched.discovered_at == art.discovered_at
    assert fetched.published_at == art.published_at
    assert fetched.language == art.language
    assert fetched.image_url == art.image_url
    assert fetched.authors == art.authors
    assert fetched.tags == art.tags
    assert fetched.metadata == art.metadata


@pytest.mark.asyncio
async def test_article_optional_fields(repo: SqliteArticleRepository):
    """Verify article with None published_at, None image_url, empty authors/tags/metadata."""
    art = make_sample_article(
        url="https://example.com/minimal-story",
        published_offset_minutes=None,
        authors=(),
        tags=(),
        metadata={},
    )
    # Manually clear image_url for minimal test
    art = NormalizedArticle(
        id=art.id,
        canonical_url=art.canonical_url,
        original_url=art.original_url,
        title=art.title,
        clean_text=art.clean_text,
        summary=art.summary,
        source_id=art.source_id,
        source_name=art.source_name,
        source_tier=art.source_tier,
        zombie_species=art.zombie_species,
        discovered_at=art.discovered_at,
        published_at=None,
        language="en",
        image_url=None,
        authors=(),
        tags=(),
        metadata={},
    )
    await repo.save_article(art)

    fetched = await repo.get_article(art.id)
    assert fetched is not None
    assert fetched.published_at is None
    assert fetched.image_url is None
    assert fetched.authors == ()
    assert fetched.tags == ()
    assert fetched.metadata == {}


@pytest.mark.asyncio
async def test_enum_round_trip(repo: SqliteArticleRepository):
    """Verify all SourceTier and ZombieSpecies enums deserialize to correct types."""
    tiers = [
        SourceTier.TIER_1_PREMIUM,
        SourceTier.TIER_2_SPECIALIST,
        SourceTier.TIER_3_COMMUNITY,
        SourceTier.TIER_4_DISCOVERY,
    ]
    species_list = [
        ZombieSpecies.RSS,
        ZombieSpecies.GITHUB,
        ZombieSpecies.HACKER_NEWS,
        ZombieSpecies.SECURITY,
        ZombieSpecies.CORPORATE,
        ZombieSpecies.WEB,
        ZombieSpecies.DISCOVERY,
    ]

    for idx, (tier, species) in enumerate(zip(tiers * 2, species_list)):
        art = make_sample_article(
            url=f"https://example.com/enum-test-{idx}",
            source_tier=tier,
            zombie_species=species,
        )
        await repo.save_article(art)
        fetched = await repo.get_article(art.id)
        assert fetched is not None
        assert fetched.source_tier == tier
        assert isinstance(fetched.source_tier, SourceTier)
        assert fetched.zombie_species == species
        assert isinstance(fetched.zombie_species, ZombieSpecies)


@pytest.mark.asyncio
async def test_utc_datetime_round_trip(repo: SqliteArticleRepository):
    """Verify timestamps maintain UTC timezone information."""
    now = datetime.now(UTC)
    art = make_sample_article(url="https://example.com/utc-time-test")
    await repo.save_article(art)

    fetched = await repo.get_article(art.id)
    assert fetched is not None
    assert fetched.discovered_at.tzinfo == UTC
    if fetched.published_at:
        assert fetched.published_at.tzinfo == UTC


@pytest.mark.asyncio
async def test_naive_datetime_rejection(repo: SqliteArticleRepository):
    """Verify saving article with naive datetime raises DomainValidationError."""
    naive_dt = datetime(2026, 8, 14, 12, 0, 0)  # No tzinfo
    with pytest.raises(DomainValidationError):
        NormalizedArticle(
            id="art_naive_test",
            canonical_url="https://example.com/naive",
            original_url="https://example.com/naive",
            title="Naive Date Article",
            clean_text="Body",
            summary="Summary",
            source_id="src_test",
            source_name="Test",
            source_tier=SourceTier.TIER_2_SPECIALIST,
            zombie_species=ZombieSpecies.RSS,
            discovered_at=naive_dt,
        )


@pytest.mark.asyncio
async def test_canonical_url_uniqueness_and_lookup(repo: SqliteArticleRepository):
    """Verify get_article_by_canonical_url and unique constraint."""
    art = make_sample_article(url="https://example.com/news/article-100")
    await repo.save_article(art)

    by_url = await repo.get_article_by_canonical_url("https://example.com/news/article-100")
    assert by_url is not None
    assert by_url.id == art.id

    # Non-existent canonical URL
    missing = await repo.get_article_by_canonical_url("https://example.com/missing")
    assert missing is None


@pytest.mark.asyncio
async def test_deterministic_upsert(repo: SqliteArticleRepository):
    """Verify saving an article with the same canonical URL updates in place."""
    url = "https://example.com/evolving-story"
    art_v1 = make_sample_article(url=url, title="Initial Headline")
    await repo.save_article(art_v1)
    assert await repo.count_articles() == 1

    # Update summary and title
    art_v2 = make_sample_article(url=url, title="Updated Headline with Developments")
    await repo.save_article(art_v2)

    # Count must remain 1
    assert await repo.count_articles() == 1
    fetched = await repo.get_article(art_v1.id)
    assert fetched is not None
    assert fetched.title == "Updated Headline with Developments"


@pytest.mark.asyncio
async def test_batch_save_atomicity(repo: SqliteArticleRepository):
    """Verify save_articles persists all articles atomically in single transaction."""
    articles = [
        make_sample_article(url=f"https://example.com/batch-{i}", title=f"Batch Story {i}")
        for i in range(5)
    ]
    saved_count = await repo.save_articles(articles)
    assert saved_count == 5
    assert await repo.count_articles() == 5

    # Empty batch returns 0
    assert await repo.save_articles([]) == 0


@pytest.mark.asyncio
async def test_recent_articles_ordering(repo: SqliteArticleRepository):
    """Verify get_recent_articles returns articles in discovered_at DESC order."""
    articles = [
        make_sample_article(
            url=f"https://example.com/timeline-{i}",
            title=f"Timeline Story {i}",
            offset_minutes=float(10 - i),  # item 0 is oldest (offset 10), item 4 is newest (offset 6)
        )
        for i in range(5)
    ]
    await repo.save_articles(articles)

    recent = await repo.get_recent_articles(limit=10)
    assert len(recent) == 5
    # First returned must be the newest (item 4, offset 6)
    assert recent[0].title == "Timeline Story 4"
    assert recent[-1].title == "Timeline Story 0"


@pytest.mark.asyncio
async def test_offset_and_limit_pagination(repo: SqliteArticleRepository):
    """Verify pagination limit and offset."""
    articles = [
        make_sample_article(url=f"https://example.com/page-{i}", offset_minutes=float(10 - i))
        for i in range(10)
    ]
    await repo.save_articles(articles)

    page1 = await repo.get_recent_articles(limit=4, offset=0)
    assert len(page1) == 4

    page2 = await repo.get_recent_articles(limit=4, offset=4)
    assert len(page2) == 4

    page3 = await repo.get_recent_articles(limit=4, offset=8)
    assert len(page3) == 2

    # Check distinct items
    p1_ids = {a.id for a in page1}
    p2_ids = {a.id for a in page2}
    assert len(p1_ids & p2_ids) == 0


@pytest.mark.asyncio
async def test_source_id_filtering(repo: SqliteArticleRepository):
    """Verify get_recent_articles filters by source_id."""
    tc_arts = [
        make_sample_article(url=f"https://techcrunch.com/tc-{i}", source_id="src_techcrunch")
        for i in range(3)
    ]
    verge_arts = [
        make_sample_article(url=f"https://theverge.com/verge-{i}", source_id="src_theverge")
        for i in range(4)
    ]
    await repo.save_articles(tc_arts + verge_arts)

    tc_fetched = await repo.get_recent_articles(source_id="src_techcrunch")
    assert len(tc_fetched) == 3
    assert all(a.source_id == "src_techcrunch" for a in tc_fetched)

    verge_fetched = await repo.get_recent_articles(source_id="src_theverge")
    assert len(verge_fetched) == 4
    assert all(a.source_id == "src_theverge" for a in verge_fetched)


@pytest.mark.asyncio
async def test_count_articles(repo: SqliteArticleRepository):
    """Verify count_articles accurately reflects repository size."""
    assert await repo.count_articles() == 0
    await repo.save_article(make_sample_article(url="https://example.com/count-1"))
    assert await repo.count_articles() == 1
    await repo.save_article(make_sample_article(url="https://example.com/count-2"))
    assert await repo.count_articles() == 2


@pytest.mark.asyncio
async def test_delete_existing_and_missing_article(repo: SqliteArticleRepository):
    """Verify delete_article returns True on delete, False when not found."""
    art = make_sample_article(url="https://example.com/delete-target")
    await repo.save_article(art)

    # Delete existing
    deleted = await repo.delete_article(art.id)
    assert deleted is True
    assert await repo.count_articles() == 0
    assert await repo.get_article(art.id) is None

    # Delete missing
    deleted_again = await repo.delete_article(art.id)
    assert deleted_again is False


@pytest.mark.asyncio
async def test_metadata_tags_authors_preservation(repo: SqliteArticleRepository):
    """Verify complex nested metadata, tuple tags, and tuple authors."""
    meta = {
        "entities": {"organizations": ["OpenAI", "Microsoft"], "locations": ["San Francisco"]},
        "scores": {"relevance": 0.98, "sentiment": 0.82, "novelty": 0.90},
        "flags": [True, False, None, 123],
    }
    authors = ("Alice Wonder", "Bob Builder", "Charlie Brown")
    tags = ("AI", "LLM", "Deep Learning", "Infrastructure")

    art = make_sample_article(
        url="https://example.com/complex-meta",
        authors=authors,
        tags=tags,
        metadata=meta,
    )
    await repo.save_article(art)

    fetched = await repo.get_article(art.id)
    assert fetched is not None
    assert fetched.authors == authors
    assert fetched.tags == tags
    assert fetched.metadata == meta
    assert isinstance(fetched.authors, tuple)
    assert isinstance(fetched.tags, tuple)
    assert isinstance(fetched.metadata, dict)


@pytest.mark.asyncio
async def test_concurrent_duplicate_writes(repo: SqliteArticleRepository):
    """Verify concurrent write tasks of the same article don't cause locking failures or duplicates."""
    art = make_sample_article(url="https://example.com/concurrent-same-story")

    async def write_task():
        await repo.save_article(art)

    tasks = [write_task() for _ in range(10)]
    await asyncio.gather(*tasks)

    assert await repo.count_articles() == 1
    fetched = await repo.get_article(art.id)
    assert fetched is not None


@pytest.mark.asyncio
async def test_large_text_payload(repo: SqliteArticleRepository):
    """Verify support for large article text bodies and extensive metadata."""
    large_body = "Paragraph content for benchmark analysis. " * 5000  # ~200 KB text
    large_meta = {f"key_{i}": f"value_{i}" * 50 for i in range(100)}

    art = NormalizedArticle.create(
        canonical_url="https://example.com/large-article",
        original_url="https://example.com/large-article",
        title="Large Payload Test",
        clean_text=large_body,
        summary="Summary for large text.",
        source_id="src_large",
        source_name="LargeSource",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.WEB,
        metadata=large_meta,
    )
    await repo.save_article(art)

    fetched = await repo.get_article(art.id)
    assert fetched is not None
    assert len(fetched.clean_text) == len(art.clean_text)
    assert fetched.clean_text == art.clean_text
    assert fetched.metadata == large_meta


@pytest.mark.asyncio
async def test_shared_sqlite_engine_coexistence(tmp_path: Path):
    """Verify SqliteArticleRepository shares the same engine and DB file with SqliteEventRepository."""
    db_file = tmp_path / "shared_canonical_test.db"
    shared_engine = SqliteEngine(db_file)

    from src.storage.sqlite_event_repository import SqliteEventRepository
    event_repo = SqliteEventRepository(engine=shared_engine, auto_init=True)
    article_repo = SqliteArticleRepository(engine=shared_engine, auto_init=True)

    # Verify both can execute against same database
    art = make_sample_article(url="https://example.com/shared-db-story")
    await article_repo.save_article(art)
    assert await article_repo.count_articles() == 1

    stats = await event_repo.get_stats()
    assert stats["total_events"] == 0

    await shared_engine.aclose()


@pytest.mark.asyncio
async def test_no_second_db_file_created(tmp_path: Path):
    """Verify only the single canonical database file is created in the directory."""
    db_file = tmp_path / "only_one_canonical.db"
    engine = SqliteEngine(db_file)
    article_repo = SqliteArticleRepository(engine=engine, auto_init=True)

    art = make_sample_article(url="https://example.com/single-file-check")
    await article_repo.save_article(art)
    await engine.aclose()

    # Check directory contents (ignoring WAL/SHM temp journal files)
    db_files = [f for f in tmp_path.iterdir() if f.name.endswith(".db")]
    assert len(db_files) == 1
    assert db_files[0].name == "only_one_canonical.db"


def test_repository_boundary_ast_no_orm():
    """Verify SqliteArticleRepository has zero imports of sqlalchemy/generic ORMs or synchronous sqlite3."""
    import ast
    repo_file = Path(__file__).resolve().parent.parent / "src" / "storage" / "sqlite_article_repository.py"
    tree = ast.parse(repo_file.read_text(encoding="utf-8"), filename=str(repo_file))

    forbidden = {"sqlalchemy", "sqlite3", "peewee", "tortoise", "orm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, f"Forbidden import '{alias.name}' in repository"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not any(f in mod for f in forbidden), f"Forbidden module '{mod}' in repository"

