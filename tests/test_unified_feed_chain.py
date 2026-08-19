"""
Unit & Integration Tests for Unified Feed Chain.
"""

import asyncio
from datetime import datetime, UTC
import os
from pathlib import Path
import tempfile
import pytest

from src.core.types import Article, SourceTier
from src.engine.source_registry import SourceRegistry, SourceDescriptor, SourceType
from src.engine.dedup_gate import DedupGate, canonicalize_url, normalize_title
from src.engine.quality_gate import QualityGate
from src.bypass.bypass_resolver import BypassResolver, is_challenge_page
from src.engine.feed_chain import FeedChain
from src.engine.cyclic_scheduler import CyclicSourceScheduler


def test_url_canonicalization():
    url1 = "HTTPS://News.YCombinator.COM/item?id=123&utm_source=twitter&ref=blog"
    url2 = "https://news.ycombinator.com/item?id=123"
    assert canonicalize_url(url1) == canonicalize_url(url2)


def test_dedup_gate_url_and_title():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_dedup.sqlite"
        gate = DedupGate(db_path=db_path, threshold=0.8)

        art1 = Article(
            id="art1",
            url="https://example.com/ai-breakthrough?utm_source=news",
            title="Massive Breakthrough in Quantum AI Computing Announced",
            content="Content here",
            summary="Summary",
            source="Example",
            source_tier=SourceTier.TIER_1
        )
        assert gate.check_and_add(art1) is False  # Accepted

        # Exact canonical URL duplicate check
        art2 = Article(
            id="art2",
            url="https://example.com/ai-breakthrough?utm_medium=email",
            title="Different Title",
            content="Content",
            summary="Summary",
            source="Example",
            source_tier=SourceTier.TIER_1
        )
        assert gate.check_and_add(art2) is True  # Rejected (URL duplicate)

        # Title MinHash duplicate check
        art3 = Article(
            id="art3",
            url="https://another-domain.com/story-99",
            title="Massive Breakthrough in Quantum AI Computing Announced!",
            content="Content",
            summary="Summary",
            source="Another",
            source_tier=SourceTier.TIER_1
        )
        assert gate.check_and_add(art3) is True  # Rejected (Title MinHash duplicate)


def test_quality_gate():
    gate = QualityGate()
    good_article = Article(
        id="good1",
        url="https://techcrunch.com/2026/08/01/ai-agent-breakthrough",
        title="New Open Source AI Agent Architecture Released by DeepMind",
        content="Artificial Intelligence developers released a new framework...",
        summary="AI agent release",
        source="TechCrunch",
        source_tier=SourceTier.TIER_1,
        published_at=datetime.now(UTC)
    )
    assert gate.check(good_article) is True

    spam_article = Article(
        id="spam1",
        url="https://spam.com/buy-now",
        title="Cheap Casino Online Free Money",
        content="Click here for cheap poker games",
        summary="Spam",
        source="SpamSite",
        source_tier=SourceTier.TIER_4
    )
    assert gate.check(spam_article) is False


def test_challenge_page_detection():
    html_challenge = "<html><body><h1>Just a moment...</h1><p>Checking your browser before accessing the site.</p></body></html>"
    assert is_challenge_page(html_challenge) is True

    html_normal = "<html><body><h1>Tech News Daily</h1><p>Python 3.14 released with sub-interpreters.</p></body></html>"
    assert is_challenge_page(html_normal) is False


@pytest.mark.asyncio
async def test_feed_chain_push_and_drain():
    chain = FeedChain()
    received = []

    def on_article(art: Article):
        received.append(art)

    chain.subscribe(on_article)

    art = Article(
        id="a1",
        url="https://example.com/1",
        title="Test Article 1",
        content="", summary="", source="Test", source_tier=SourceTier.TIER_1
    )
    await chain.push(art)

    assert len(received) == 1
    assert received[0].id == "a1"

    drained = chain.drain()
    assert len(drained) == 1
    assert drained[0].id == "a1"
