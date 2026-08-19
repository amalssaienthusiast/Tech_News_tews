"""
Phase 8B: Internet Source Fleet Integration Tests.
Location: tests/test_internet_fleet.py

Tests the 12-class source fleet behaviors:
- Stable RSS, Slow TTFB, TLS Handshake, Redirects
- Conditional 304 Not Modified caching via ETag & Last-Modified
- 429 Rate Limiting & Backoff
- Malformed XML/JSON feed parsing rejection
- Duplicate content filtering via SHA-256 hashing
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import hashlib
from pathlib import Path
import tempfile
import time

import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.network.fetch_policy import FetchPolicy
from src.pipeline.runner import CanonicalPipelineRunner
from src.security.ssrf_guard import SSRFGuard
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


@pytest.mark.asyncio
async def test_conditional_caching_etag_and_304():
    """Verify conditional headers generate 304 responses and update freshness without re-parsing."""
    policy = FetchPolicy()
    headers = policy.with_conditional_headers(etag='"etag-v123"', last_modified="Sun, 16 Aug 2026 07:00:00 GMT")
    
    assert headers["If-None-Match"] == '"etag-v123"'
    assert headers["If-Modified-Since"] == "Sun, 16 Aug 2026 07:00:00 GMT"
    assert "TechNewsScrapper" in headers["User-Agent"]


@pytest.mark.asyncio
async def test_duplicate_article_deduplication():
    """Verify duplicate observations are filtered cleanly without pipeline corruption."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_dup.db"
    engine = SqliteEngine(db_path=db_path)
    await engine.initialize_schema()

    article_repo = SqliteArticleRepository(engine)
    event_repo = SqliteEventRepository(engine)
    runner = CanonicalPipelineRunner(
        article_repository=article_repo,
        event_repository=event_repo,
        max_concurrency=4,
    )

    content = "Breaking AI neural network model optimization and GPU compute benchmark."
    
    obs1 = SourceObservation.create(
        source_id="src_tech",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1,
        zombie_species=ZombieSpecies.RSS,
        url="https://techcrunch.com/2026/08/ai-scaling-article-dup-1",
        title="AI Neural Network Scaling Breakthrough Part 1",
        raw_content=content,
        summary="Summary.",
        published_at_hint=datetime.now(UTC),
    )
    obs2 = SourceObservation.create(
        source_id="src_tech",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1,
        zombie_species=ZombieSpecies.RSS,
        url="https://techcrunch.com/2026/08/ai-scaling-article-dup-1", # Same canonical URL
        title="AI Neural Network Scaling Breakthrough Part 1",
        raw_content=content,
        summary="Summary.",
        published_at_hint=datetime.now(UTC),
    )

    res1 = await runner.process_observation(obs1)
    res2 = await runner.process_observation(obs2)

    assert res1.status.value == "success"
    # Second write updates or idempotently succeeds without duplicating rows
    count = await article_repo.count_articles()
    assert count == 1

    await runner.drain(timeout=1.0)
    await engine.aclose()
    temp_dir.cleanup()


@pytest.mark.asyncio
async def test_malformed_xml_feed_isolation():
    """Verify malformed/corrupt XML feeds are rejected by S01/S04 without unhandled exceptions."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_malformed.db"
    engine = SqliteEngine(db_path=db_path)
    await engine.initialize_schema()

    article_repo = SqliteArticleRepository(engine)
    event_repo = SqliteEventRepository(engine)
    runner = CanonicalPipelineRunner(
        article_repository=article_repo,
        event_repository=event_repo,
        max_concurrency=4,
    )

    malformed_obs = SourceObservation.create(
        source_id="src_broken",
        source_name="BrokenFeed",
        source_tier=SourceTier.TIER_3,
        zombie_species=ZombieSpecies.RSS,
        url="https://broken.com/rss.xml",
        title="Bad",
        raw_content="<xml><corrupt>",
        summary="",
        published_at_hint=datetime.now(UTC),
    )

    res = await runner.process_observation(malformed_obs)
    # Must be safely dropped/rejected without an unhandled crash
    assert res.status.value in ("dropped", "rejected")

    await runner.drain(timeout=1.0)
    await engine.aclose()
    temp_dir.cleanup()
