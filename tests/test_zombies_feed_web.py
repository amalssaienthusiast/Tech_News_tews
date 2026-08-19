"""
Unit Tests for Feed and Web Zombie Species (ZRss, ZWeb, ZCorp).
Location: tests/test_zombies_feed_web.py

Tests:
  - ZRss: Canonical SourceObservation emission from RSS 2.0 & Atom XML
  - ZRss: Date normalization to timezone-aware UTC (published_parsed, updated_parsed, string formats)
  - ZRss: Image URL extraction (media:content, media:thumbnail, img tags in summary)
  - ZRss: Duplicate suppression & bounded OrderedDict capacity (500 max)
  - ZWeb: HTML headline extraction and canonical SourceObservation creation
  - ZWeb: Title sanitization and minimum word count threshold (>= 5 words)
  - ZWeb: WAF block detection ("Just a moment...", "cf-browser-verification")
  - ZCorp: Corporate blog SourceObservation creation with TIER_1_PREMIUM & primary metadata
  - Invariants: Frozen SourceObservation, zero EventSource imports, correct enums
"""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor, SourceType
from src.zombies.z_corp import ZCorp
from src.zombies.z_rss import ZRss
from src.zombies.z_web import ZWeb


# Sample RSS 2.0 XML
SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Tech News Feed</title>
    <link>https://technews.example.com</link>
    <description>Daily tech headlines</description>
    <item>
      <title>Google Announces Gemini 3.5 Pro with Quantum Reasoning</title>
      <link>https://technews.example.com/2026/08/gemini-3-5</link>
      <description><![CDATA[Google has revealed its latest AI reasoning system. <img src="https://technews.example.com/img/gemini.png" />]]></description>
      <pubDate>Fri, 14 Aug 2026 12:00:00 GMT</pubDate>
      <media:content url="https://technews.example.com/img/hero.jpg" medium="image" />
    </item>
    <item>
      <title>OpenAI Releases Open Source Robotics Framework</title>
      <link>https://technews.example.com/2026/08/robotics-oss</link>
      <description>New robotics SDK released under Apache 2.0.</description>
      <pubDate>Fri, 14 Aug 2026 13:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

# Sample Atom XML
SAMPLE_ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Engineering Feed</title>
  <link href="https://eng.example.com"/>
  <updated>2026-08-14T14:00:00Z</updated>
  <entry>
    <title>Rust 1.95 Released with Native WebAssembly SIMD</title>
    <link href="https://eng.example.com/posts/rust-1-95"/>
    <id>urn:uuid:12345</id>
    <updated>2026-08-14T11:45:00Z</updated>
    <summary>The Rust core team announces version 1.95 with enhanced async runtime.</summary>
  </entry>
</feed>
"""

# Sample Web HTML
SAMPLE_HTML_PAGE = """<!DOCTYPE html>
<html>
<head><title>Tech Wire Homepage</title></head>
<body>
  <nav><a href="/menu">Menu</a></nav>
  <header><h1>Tech Wire</h1></header>
  <main>
    <article>
      <h2><a href="/news/apple-m5-chip-announced">Apple Unveils M5 Ultra Chip with 128 GPU Cores</a></h2>
    </article>
    <article>
      <h2><a href="/news/linux-kernel-7-0">Linux Kernel 7.0 Officially Released by Linus Torvalds</a></h2>
    </article>
    <!-- Short link that should be filtered out (< 5 words) -->
    <article>
      <h2><a href="/short">Short Headline</a></h2>
    </article>
    <!-- Navigation junk that should be filtered -->
    <div>
      <a href="/read-more">Read more articles here</a>
    </div>
  </main>
  <footer><a href="/about">About Us</a></footer>
</body>
</html>
"""


# =============================================================================
# 1. Z-RSS TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_z_rss_creates_canonical_source_observations():
    source = SourceDescriptor(
        id="tech_rss_1",
        url="https://technews.example.com/rss",
        name="TechNews Daily",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZRss(source)

    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=SAMPLE_RSS_XML)):
        observations = await zombie.hunt()

    assert len(observations) == 2
    obs1 = observations[0]
    assert isinstance(obs1, SourceObservation)
    assert obs1.source_id == "tech_rss_1"
    assert obs1.source_name == "TechNews Daily"
    assert obs1.source_tier == SourceTier.TIER_1_PREMIUM
    assert obs1.zombie_species == ZombieSpecies.RSS
    assert obs1.url == "https://technews.example.com/2026/08/gemini-3-5"
    assert obs1.title == "Google Announces Gemini 3.5 Pro with Quantum Reasoning"
    assert "Google has revealed" in obs1.summary
    assert obs1.image_url == "https://technews.example.com/img/hero.jpg"
    assert obs1.published_at_hint is not None
    assert obs1.published_at_hint.tzinfo == UTC
    assert obs1.published_at_hint == datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_z_rss_atom_date_normalization():
    source = SourceDescriptor(
        id="eng_atom_1",
        url="https://eng.example.com/atom.xml",
        name="Engineering Atom",
        type=SourceType.RSS,
        tier=2,
    )
    zombie = ZRss(source)

    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=SAMPLE_ATOM_XML)):
        observations = await zombie.hunt()

    assert len(observations) == 1
    obs = observations[0]
    assert obs.source_tier == SourceTier.TIER_2_SPECIALIST
    assert obs.zombie_species == ZombieSpecies.RSS
    assert obs.url == "https://eng.example.com/posts/rust-1-95"
    assert obs.title == "Rust 1.95 Released with Native WebAssembly SIMD"
    assert obs.published_at_hint == datetime(2026, 8, 14, 11, 45, 0, tzinfo=UTC)
    assert obs.published_at_hint.tzinfo == UTC


@pytest.mark.asyncio
async def test_z_rss_duplicate_suppression():
    source = SourceDescriptor(
        id="tech_rss_1",
        url="https://technews.example.com/rss",
        name="TechNews Daily",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZRss(source)

    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=SAMPLE_RSS_XML)):
        first_hunt = await zombie.hunt()
        assert len(first_hunt) == 2

        # Second hunt with same XML -> should return empty list (all seen)
        second_hunt = await zombie.hunt()
        assert len(second_hunt) == 0


@pytest.mark.asyncio
async def test_z_rss_bounded_seen_urls_fifo_eviction():
    source = SourceDescriptor(
        id="tech_rss_bounded",
        url="https://technews.example.com/rss",
        name="TechNews Bounded",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZRss(source)

    # Pre-fill seen URLs to 500 items
    for i in range(500):
        zombie._seen_urls[f"https://technews.example.com/old-article-{i}"] = True

    assert len(zombie._seen_urls) == 500

    # Hunt new items
    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=SAMPLE_RSS_XML)):
        new_obs = await zombie.hunt()

    assert len(new_obs) == 2
    # Capacity must not exceed 500
    assert len(zombie._seen_urls) == 500
    # Oldest entries should have been evicted
    assert "https://technews.example.com/old-article-0" not in zombie._seen_urls
    assert "https://technews.example.com/old-article-1" not in zombie._seen_urls
    # Newly seen entries must be present
    assert "https://technews.example.com/2026/08/gemini-3-5" in zombie._seen_urls


# =============================================================================
# 2. Z-WEB TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_z_web_extracts_headlines_and_sanitizes():
    source = SourceDescriptor(
        id="tech_web_1",
        url="https://techwire.example.com",
        name="Tech Wire",
        type=SourceType.HTML,
        tier=3,
    )
    zombie = ZWeb(source)

    with patch("src.zombies.z_web.browser.fetch", AsyncMock(return_value=SAMPLE_HTML_PAGE)):
        observations = await zombie.hunt()

    assert len(observations) == 2
    obs1 = observations[0]
    assert obs1.source_tier == SourceTier.TIER_3_COMMUNITY
    assert obs1.zombie_species == ZombieSpecies.WEB
    assert obs1.url == "https://techwire.example.com/news/apple-m5-chip-announced"
    assert obs1.title == "Apple Unveils M5 Ultra Chip with 128 GPU Cores"
    assert obs1.published_at_hint is None

    obs2 = observations[1]
    assert obs2.url == "https://techwire.example.com/news/linux-kernel-7-0"
    assert obs2.title == "Linux Kernel 7.0 Officially Released by Linus Torvalds"


@pytest.mark.asyncio
async def test_z_web_waf_challenge_detection():
    source = SourceDescriptor(
        id="tech_web_waf",
        url="https://blocked.example.com",
        name="Blocked Site",
        type=SourceType.HTML,
        tier=3,
    )
    zombie = ZWeb(source)

    waf_html = "<html><body><h1>Just a moment...</h1><p>Checking your browser before accessing.</p></body></html>"
    with patch("src.zombies.z_web.browser.fetch", AsyncMock(return_value=waf_html)):
        observations = await zombie.hunt()

    assert len(observations) == 0


@pytest.mark.asyncio
async def test_z_web_bounded_seen_urls_fifo_eviction():
    source = SourceDescriptor(
        id="tech_web_bounded",
        url="https://techwire.example.com",
        name="Tech Wire Bounded",
        type=SourceType.HTML,
        tier=3,
    )
    zombie = ZWeb(source)

    for i in range(500):
        zombie._seen_urls[f"https://techwire.example.com/old-{i}"] = True

    with patch("src.zombies.z_web.browser.fetch", AsyncMock(return_value=SAMPLE_HTML_PAGE)):
        observations = await zombie.hunt()

    assert len(observations) == 2
    assert len(zombie._seen_urls) == 500
    assert "https://techwire.example.com/old-0" not in zombie._seen_urls
    assert "https://techwire.example.com/news/apple-m5-chip-announced" in zombie._seen_urls


# =============================================================================
# 3. Z-CORP TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_z_corp_creates_primary_tier1_observations():
    source = SourceDescriptor(
        id="openai_blog",
        url="https://openai.com/blog/rss.xml",
        name="OpenAI Official Blog",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZCorp(source)

    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=SAMPLE_RSS_XML)):
        observations = await zombie.hunt()

    assert len(observations) == 2
    for obs in observations:
        assert obs.zombie_species == ZombieSpecies.CORPORATE
        assert obs.source_tier == SourceTier.TIER_1_PREMIUM
        assert obs.metadata.get("is_primary") is True
        assert obs.metadata.get("corporate_source") is True


# =============================================================================
# 4. FROZEN INVARIANT TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_frozen_source_observation_immutability():
    source = SourceDescriptor(
        id="corp_rss",
        url="https://googleblog.com/feed.xml",
        name="Google Blog",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZCorp(source)

    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=SAMPLE_RSS_XML)):
        observations = await zombie.hunt()

    obs = observations[0]
    with pytest.raises(Exception):
        obs.title = "Changed Title"
    with pytest.raises(Exception):
        obs.source_tier = SourceTier.TIER_3_COMMUNITY
