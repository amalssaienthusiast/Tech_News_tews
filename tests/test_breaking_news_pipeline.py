"""
Unit & Integration Tests for Breaking News Priority Pipeline.
"""

import asyncio
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, UTC
from pathlib import Path
import pytest

from src.core.types import Article, SourceTier
from src.engine.freshness_gate import FreshnessGate, FreshnessResult
from src.engine.rejected_metadata_store import RejectedMetadataStore
from src.engine.quality_gate import QualityGate
from src.engine.dedup_gate import DedupGate
from src.engine.feed_chain import FeedChain
from src.engine.breaking_news_pipeline import BreakingNewsScanner
from main_engine import ArticleRingBuffer, SSEBroadcaster
import telegram_feeder_bot


def test_article_pipeline_tagging():
    """Verify Article dataclass supports pipeline tagging."""
    art = Article(
        id="test_art_1",
        url="https://example.com/breaking-news",
        title="Major Breakthrough in Quantum Computing Announced",
        content="Details about quantum computing breakthrough.",
        summary="A major breakthrough has been achieved.",
        source="TechCrunch",
        source_tier=SourceTier.TIER_1,
        pipeline="breaking",
    )
    d = art.to_dict()
    assert d["pipeline"] == "breaking"
    assert d["title"] == "Major Breakthrough in Quantum Computing Announced"


def test_freshness_gate():
    """Test strict ≤30min and soft ≤60min freshness verification."""
    gate = FreshnessGate(hard_cutoff_minutes=30, soft_cutoff_minutes=60)
    now = datetime.now(UTC)

    # 1. 10 mins old -> Hard Fresh
    art_fresh = Article(
        id="art_10m",
        url="https://example.com/1",
        title="Apple Launches Revolutionary AI Chip",
        content="...",
        summary="...",
        source="Ars Technica",
        source_tier=SourceTier.TIER_1,
        published_at=now - timedelta(minutes=10),
    )
    res = gate.check(art_fresh)
    assert res.is_fresh is True
    assert res.is_soft_fresh is False
    assert res.is_any_fresh is True
    assert res.confidence == 1.0
    assert res.rejection_reason is None

    # 2. 45 mins old -> Soft Fresh (30-60m)
    art_soft = Article(
        id="art_45m",
        url="https://example.com/2",
        title="OpenAI Releases New Frontier Model",
        content="...",
        summary="...",
        source="TechCrunch",
        source_tier=SourceTier.TIER_1,
        published_at=now - timedelta(minutes=45),
    )
    res = gate.check(art_soft)
    assert res.is_fresh is False
    assert res.is_soft_fresh is True
    assert res.is_any_fresh is True

    # 3. 90 mins old -> Stale
    art_stale = Article(
        id="art_90m",
        url="https://example.com/3",
        title="Old Tech News from Hours Ago",
        content="...",
        summary="...",
        source="Wired",
        source_tier=SourceTier.TIER_1,
        published_at=now - timedelta(minutes=90),
    )
    res = gate.check(art_stale)
    assert res.is_fresh is False
    assert res.is_soft_fresh is False
    assert res.is_any_fresh is False
    assert "stale" in res.rejection_reason

    # 4. No timestamp -> Rejected
    art_no_date = Article(
        id="art_nodate",
        url="https://example.com/4",
        title="Article With No Date",
        content="...",
        summary="...",
        source="Custom",
        source_tier=SourceTier.TIER_3,
        published_at=None,
        scraped_at=None,
    )
    res = gate.check(art_no_date)
    assert res.is_any_fresh is False
    assert res.rejection_reason == "no_timestamp"


def test_rejected_metadata_store():
    """Verify storing, querying, and stats in RejectedMetadataStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rejected.sqlite"
        store = RejectedMetadataStore(db_path=db_path)

        art = Article(
            id="rej_1",
            url="https://example.com/spam-post",
            title="Spam Title Here",
            content="...",
            summary="...",
            source="Unknown",
            source_tier=SourceTier.TIER_3,
        )

        # Store rejection
        stored = store.store(art, rejection_reason="spam", rejection_pipeline="breaking")
        assert stored is True

        # Check existence
        assert store.is_known_rejected("rej_1") is True
        assert store.is_known_rejected("non_existent") is False
        assert store.is_url_known_rejected("https://example.com/spam-post") is True

        # Stats
        stats = store.get_stats()
        assert stats["total_rejected"] == 1
        assert stats["by_reason"]["spam"] == 1
        assert stats["by_pipeline"]["breaking"] == 1


def test_quality_gate_strict():
    """Verify QualityGate.check_strict logic."""
    gate = QualityGate()

    # Short title -> reject
    short_art = Article(
        id="s1",
        url="https://example.com/s",
        title="AI news",  # < 15 chars
        content="Content",
        summary="Summary",
        source="Ars Technica",
        source_tier=SourceTier.TIER_1,
    )
    assert gate.check_strict(short_art) == "title_too_short"

    # Good tech title -> pass
    good_art = Article(
        id="g1",
        url="https://example.com/g",
        title="Google DeepMind Announces Gemini 2.0 Flash Architecture",
        content="Technical details on the new AI architecture.",
        summary="Google announces Gemini 2.0.",
        source="Ars Technica",
        source_tier=SourceTier.TIER_1,
    )
    assert gate.check_strict(good_art) == "pass"


def test_article_ring_buffer_pipeline_filtering():
    """Verify ArticleRingBuffer filtered queries by pipeline."""
    buf = ArticleRingBuffer(capacity=100)

    art1 = Article(
        id="b1",
        url="https://example.com/b1",
        title="Breaking Headline 1",
        content="...",
        summary="...",
        source="TechCrunch",
        source_tier=SourceTier.TIER_1,
        pipeline="breaking",
    )
    art2 = Article(
        id="s1",
        url="https://example.com/s1",
        title="Standard Headline 2",
        content="...",
        summary="...",
        source="Wired",
        source_tier=SourceTier.TIER_1,
        pipeline="standard",
    )

    buf.push(art1)
    buf.push(art2)

    # Filter breaking only
    breaking_only = buf.since_filtered(pipeline="breaking")
    assert len(breaking_only) == 1
    assert breaking_only[0]["id"] == "b1"
    assert breaking_only[0]["pipeline"] == "breaking"

    # Filter standard only
    standard_only = buf.since_filtered(pipeline="standard")
    assert len(standard_only) == 1
    assert standard_only[0]["id"] == "s1"
    assert standard_only[0]["pipeline"] == "standard"

    # All
    all_arts = buf.since_filtered(pipeline=None)
    assert len(all_arts) == 2


def test_telegram_bot_breaking_format():
    """Verify Telegram formatting adds the 🔴🔴🔴 BREAKING NEWS badge."""
    art_data = telegram_feeder_bot.ArticleData(
        id="tg1",
        url="https://news.ycombinator.com/item?id=123",
        title="Critical Zero-Day Vulnerability Discovered in Linux Kernel",
        summary="A major vulnerability was disclosed today.",
        source="Hacker News",
        pipeline="breaking",
    )

    pub = telegram_feeder_bot.TelegramPublisher(bot_token="test", chat_id="test")
    msg = pub.format_article_message(art_data)

    assert "🔴🔴🔴 <b>BREAKING NEWS</b> 🔴🔴🔴" in msg
    assert "Critical Zero-Day Vulnerability Discovered in Linux Kernel" in msg
    assert art_data.is_breaking is True

    # Standard article
    art_standard = telegram_feeder_bot.ArticleData(
        id="tg2",
        url="https://news.ycombinator.com/item?id=124",
        title="Review of the Best Laptops for Developers in 2026",
        summary="Here is a roundup of top laptops.",
        source="Hacker News",
        pipeline="standard",
    )
    msg_std = pub.format_article_message(art_standard)
    assert "🔴🔴🔴 <b>BREAKING NEWS</b> 🔴🔴🔴" not in msg_std
    assert "📰" in msg_std
    assert art_standard.is_breaking is False
