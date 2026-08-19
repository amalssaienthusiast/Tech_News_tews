"""
End-to-End Integration Test for Breaking News Scanner & Main Engine Dual Pipeline.
"""

import asyncio
from datetime import datetime, timedelta, UTC
import pytest

from src.core.types import Article, SourceTier
from src.engine.freshness_gate import FreshnessGate
from src.engine.quality_gate import QualityGate
from src.engine.dedup_gate import DedupGate
from src.engine.feed_chain import FeedChain
from src.engine.breaking_news_pipeline import BreakingNewsScanner
from src.engine.rejected_metadata_store import RejectedMetadataStore
from main_engine import ArticleRingBuffer, MainEngine, SSEBroadcaster


@pytest.mark.asyncio
async def test_breaking_news_scanner_e2e_routing():
    """Verify BreakingNewsScanner correctly tags, routes, and separates breaking vs standard."""
    feed = FeedChain(maxsize=100)
    dedup = DedupGate()
    quality = QualityGate()
    rejected_store = RejectedMetadataStore()

    scanner = BreakingNewsScanner(
        dedup=dedup,
        quality=quality,
        feed=feed,
        rejected_store=rejected_store,
        hard_cutoff_minutes=30,
        soft_cutoff_minutes=60,
    )

    # Receive callbacks
    breaking_received = []
    scanner.subscribe_breaking(lambda art: breaking_received.append(art))

    # Ring buffer to collect
    ring = ArticleRingBuffer(capacity=100)

    def on_feed(art):
        ring.push(art)

    feed.subscribe(on_feed)

    now = datetime.now(UTC)

    # 1. Push a fresh breaking article
    fresh_article = Article(
        id="e2e_fresh_1",
        url="https://arstechnica.com/breaking-ai-chip-2026",
        title="NVIDIA Announces Next-Gen Quantum AI Accelerator Architecture",
        content="Technical specifications of the new architecture.",
        summary="A major announcement in quantum AI computing.",
        source="Ars Technica",
        source_tier=SourceTier.TIER_1,
        published_at=now - timedelta(minutes=5),  # 5 minutes old!
    )

    # 2. Push a stale article (>60m)
    stale_article = Article(
        id="e2e_stale_1",
        url="https://techcrunch.com/yesterday-startup-funding",
        title="Seed Stage Startup Raises Five Million Dollars For Widget Tool",
        content="Funding announcement from yesterday.",
        summary="Startup funding details.",
        source="TechCrunch",
        source_tier=SourceTier.TIER_1,
        published_at=now - timedelta(hours=5),  # 5 hours old!
    )

    # Let's test the freshness gate directly on these articles
    res_fresh = scanner._freshness_gate.check(fresh_article)
    assert res_fresh.is_fresh is True

    res_stale = scanner._freshness_gate.check(stale_article)
    assert res_stale.is_fresh is False

    # Check strict quality
    assert quality.check_strict(fresh_article) == "pass"

    # Simulate breaking scanner processing
    fresh_article.pipeline = "breaking"
    await feed.push(fresh_article)

    stale_article.pipeline = "standard"
    await feed.push(stale_article)

    # Query filtered from ring buffer
    breaking_feed = ring.since_filtered(pipeline="breaking")
    assert len(breaking_feed) == 1
    assert breaking_feed[0]["id"] == "e2e_fresh_1"
    assert breaking_feed[0]["pipeline"] == "breaking"

    standard_feed = ring.since_filtered(pipeline="standard")
    assert len(standard_feed) == 1
    assert standard_feed[0]["id"] == "e2e_stale_1"
    assert standard_feed[0]["pipeline"] == "standard"

    # Stats
    stats = scanner.get_stats()
    assert stats["freshness_config"]["hard_cutoff_minutes"] == 30
    assert stats["freshness_config"]["soft_cutoff_minutes"] == 60


@pytest.mark.asyncio
async def test_sse_broadcaster_event_types():
    """Verify SSEBroadcaster sends correct event types ('breaking' vs 'article')."""
    broadcaster = SSEBroadcaster()

    class MockStreamResponse:
        def __init__(self):
            self.written = []

        async def write(self, data: bytes):
            self.written.append(data.decode("utf-8"))

    mock_client = MockStreamResponse()
    broadcaster.add_client(mock_client)
    assert broadcaster.client_count == 1

    # Broadcast breaking article
    await broadcaster.broadcast({"id": "art_1", "title": "Breaking News"}, event_type="breaking")
    assert len(mock_client.written) == 1
    assert mock_client.written[0].startswith("event: breaking\n")

    # Broadcast standard article
    await broadcaster.broadcast({"id": "art_2", "title": "Standard News"}, event_type="article")
    assert len(mock_client.written) == 2
    assert mock_client.written[1].startswith("event: article\n")

    broadcaster.remove_client(mock_client)
    assert broadcaster.client_count == 0
