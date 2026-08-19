"""
Unit & Integration Tests for Phase 5A Storage Engine.
Location: tests/test_storage_engine.py

Verifies:
- Schema DDL execution and table/index creation
- PRAGMA configuration (WAL, foreign_keys=ON, busy_timeout=10000)
- Primary keys, foreign keys, and cascading deletes
- Unique constraints (UNIQUE(event_id, url))
- Transactional atomicity (commit & rollback)
- Asynchronous context manager lifecycles
- Idempotent schema initialization
- Timestamp and JSON serialization formatting
"""

from datetime import datetime, UTC
import json
from pathlib import Path
import sqlite3
import pytest
import aiosqlite

from src.storage.sqlite_engine import SqliteEngine
from src.storage.protocols import (
    EventRepositoryProtocol,
    ArticleRepositoryProtocol,
    SourceHealthRepositoryProtocol,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide an isolated temporary database path."""
    return tmp_path / "test_canonical_events.db"


@pytest.fixture
async def engine(temp_db_path: Path) -> SqliteEngine:
    """Provide an initialized SQLite engine on a temporary database."""
    eng = SqliteEngine(temp_db_path)
    await eng.initialize_schema()
    yield eng
    await eng.aclose()


@pytest.mark.asyncio
async def test_schema_creation_tables_exist(engine: SqliteEngine):
    """Verify that all 5 canonical tables exist following initialization."""
    expected_tables = {
        "canonical_events",
        "canonical_event_sources",
        "canonical_event_timeline",
        "canonical_articles",
        "canonical_source_health",
    }

    async with engine.connect() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
        rows = await cursor.fetchall()
        created_tables = {row["name"] for row in rows}

    assert expected_tables.issubset(created_tables), f"Missing tables: {expected_tables - created_tables}"


@pytest.mark.asyncio
async def test_pragmas_configured_correctly(engine: SqliteEngine):
    """Verify that WAL mode, foreign keys, and busy timeout are configured on all connections."""
    async with engine.connect() as conn:
        # Journal mode (WAL)
        cur = await conn.execute("PRAGMA journal_mode;")
        row = await cur.fetchone()
        assert row[0].lower() == "wal"

        # Foreign keys enabled (1)
        cur = await conn.execute("PRAGMA foreign_keys;")
        row = await cur.fetchone()
        assert row[0] == 1

        # Busy timeout (10000ms)
        cur = await conn.execute("PRAGMA busy_timeout;")
        row = await cur.fetchone()
        assert row[0] == 10000


@pytest.mark.asyncio
async def test_idempotent_schema_initialization(engine: SqliteEngine):
    """Verify that calling initialize_schema multiple times succeeds without error."""
    # Run a second and third initialization
    await engine.initialize_schema()
    await engine.initialize_schema()

    async with engine.connect() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM canonical_events;")
        row = await cur.fetchone()
        assert row[0] == 0


@pytest.mark.asyncio
async def test_foreign_key_and_cascade_delete(engine: SqliteEngine):
    """Verify foreign key enforcement and ON DELETE CASCADE on child entities."""
    event_id = "evt_test_cascade_01"
    now_iso = datetime.now(UTC).isoformat()

    async with engine.transaction() as conn:
        # Insert parent event
        await conn.execute(
            """
            INSERT INTO canonical_events (id, headline, first_seen, last_updated, entities, topics)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (event_id, "Cascade Test Event", now_iso, now_iso, json.dumps(["TestCorp"]), json.dumps(["AI"])),
        )

        # Insert child source
        await conn.execute(
            """
            INSERT INTO canonical_event_sources (event_id, article_id, url, title, source_name, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (event_id, "art_01", "https://example.com/cascade-1", "Cascade Article", "TestSource", now_iso),
        )

        # Insert child timeline
        await conn.execute(
            """
            INSERT INTO canonical_event_timeline (event_id, timestamp, headline, source_name, source_url)
            VALUES (?, ?, ?, ?, ?);
            """,
            (event_id, now_iso, "Cascade Timeline Update", "TestSource", "https://example.com/cascade-1"),
        )

    # Verify rows exist
    async with engine.connect() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM canonical_event_sources WHERE event_id = ?;", (event_id,))
        assert (await cur.fetchone())[0] == 1

        cur = await conn.execute("SELECT COUNT(*) FROM canonical_event_timeline WHERE event_id = ?;", (event_id,))
        assert (await cur.fetchone())[0] == 1

    # Delete parent event
    async with engine.transaction() as conn:
        await conn.execute("DELETE FROM canonical_events WHERE id = ?;", (event_id,))

    # Verify cascading delete purged child rows
    async with engine.connect() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM canonical_event_sources WHERE event_id = ?;", (event_id,))
        assert (await cur.fetchone())[0] == 0

        cur = await conn.execute("SELECT COUNT(*) FROM canonical_event_timeline WHERE event_id = ?;", (event_id,))
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_foreign_key_violation_rejection(engine: SqliteEngine):
    """Verify that inserting a child row without a valid parent fails."""
    now_iso = datetime.now(UTC).isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        async with engine.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO canonical_event_sources (event_id, article_id, url, title, source_name, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                ("non_existent_event_id", "art_bad", "https://example.com/bad", "Bad", "Src", now_iso),
            )


@pytest.mark.asyncio
async def test_unique_constraint_on_event_sources(engine: SqliteEngine):
    """Verify UNIQUE(event_id, url) constraint on canonical_event_sources."""
    event_id = "evt_test_unique_01"
    url = "https://example.com/unique-article"
    now_iso = datetime.now(UTC).isoformat()

    async with engine.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO canonical_events (id, headline, first_seen, last_updated)
            VALUES (?, ?, ?, ?);
            """,
            (event_id, "Unique Test Event", now_iso, now_iso),
        )

        await conn.execute(
            """
            INSERT INTO canonical_event_sources (event_id, article_id, url, title, source_name, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (event_id, "art_u1", url, "Article 1", "Src", now_iso),
        )

    # Attempt inserting the same URL for the same event should fail
    with pytest.raises(sqlite3.IntegrityError):
        async with engine.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO canonical_event_sources (event_id, article_id, url, title, source_name, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (event_id, "art_u2", url, "Article Duplicate URL", "Src", now_iso),
            )


@pytest.mark.asyncio
async def test_transaction_rollback_on_error(engine: SqliteEngine):
    """Verify that an exception inside engine.transaction() rolls back all operations."""
    event_id = "evt_rollback_01"
    now_iso = datetime.now(UTC).isoformat()

    try:
        async with engine.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO canonical_events (id, headline, first_seen, last_updated)
                VALUES (?, ?, ?, ?);
                """,
                (event_id, "Will Rollback", now_iso, now_iso),
            )
            # Intentionally raise an error to trigger rollback
            raise RuntimeError("Simulated transaction error")
    except RuntimeError:
        pass

    # Verify event was NOT persisted
    async with engine.connect() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM canonical_events WHERE id = ?;", (event_id,))
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_canonical_articles_table_operations(engine: SqliteEngine):
    """Verify operations on canonical_articles table."""
    art_id = "art_test_1234"
    canon_url = "https://example.com/canonical-test"
    now_iso = datetime.now(UTC).isoformat()

    async with engine.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO canonical_articles (
                id, canonical_url, original_url, title, clean_text, summary,
                source_id, source_name, source_tier, zombie_species, discovered_at,
                authors, tags, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                art_id,
                canon_url,
                "https://example.com/canonical-test?utm_source=twitter",
                "Canonical Article Test",
                "Clean text body content.",
                "Summary snippet.",
                "src_rss_01",
                "TechNews",
                "tier_1_premium",
                "z_rss",
                now_iso,
                json.dumps(["Alice", "Bob"]),
                json.dumps(["Python", "SQLite"]),
                json.dumps({"word_count": 42}),
            ),
        )

    # Fetch and verify
    row = await engine.fetchone("SELECT * FROM canonical_articles WHERE id = ?;", (art_id,))
    assert row is not None
    assert row["canonical_url"] == canon_url
    assert row["source_tier"] == "tier_1_premium"
    assert json.loads(row["authors"]) == ["Alice", "Bob"]
    assert json.loads(row["metadata"])["word_count"] == 42


@pytest.mark.asyncio
async def test_canonical_source_health_table_operations(engine: SqliteEngine):
    """Verify operations on canonical_source_health table."""
    source_id = "src_hn_01"
    now_iso = datetime.now(UTC).isoformat()

    async with engine.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO canonical_source_health (
                source_id, source_url, source_name, status,
                consecutive_failures, consecutive_successes, last_attempt, last_success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (source_id, "https://news.ycombinator.com", "Hacker News", "healthy", 0, 5, now_iso, now_iso),
        )

    row = await engine.fetchone("SELECT * FROM canonical_source_health WHERE source_id = ?;", (source_id,))
    assert row is not None
    assert row["source_name"] == "Hacker News"
    assert row["status"] == "healthy"
    assert row["consecutive_successes"] == 5


@pytest.mark.asyncio
async def test_direct_async_context_manager_lifecycle(temp_db_path: Path):
    """Verify engine async context manager (__aenter__/__aexit__) connection handling."""
    engine = SqliteEngine(temp_db_path)
    await engine.initialize_schema()

    async with engine as conn:
        cur = await conn.execute("SELECT 1;")
        res = await cur.fetchone()
        assert res[0] == 1

    await engine.aclose()


def test_protocols_importable_and_typecheckable():
    """Verify that all protocols are valid typing protocols."""
    assert hasattr(EventRepositoryProtocol, "__abstractmethods__") or hasattr(EventRepositoryProtocol, "_is_protocol")
    assert hasattr(ArticleRepositoryProtocol, "__abstractmethods__") or hasattr(ArticleRepositoryProtocol, "_is_protocol")
    assert hasattr(SourceHealthRepositoryProtocol, "__abstractmethods__") or hasattr(SourceHealthRepositoryProtocol, "_is_protocol")
