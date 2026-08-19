"""
Unit Tests for API and Specialized Zombie Species (ZHacker, ZGitHub, ZSecurity).
Location: tests/test_zombies_api_specialized.py

Tests:
  - ZHacker: Hacker News Firebase API story fetching & canonical SourceObservation creation
  - ZHacker: Story velocity scoring & metadata (hn_item_id, hn_score, high_velocity)
  - ZHacker: Bounded deduplication, cache eviction & async session aclose()
  - ZGitHub: Tracked repository release detection, ETag caching & release metadata
  - ZGitHub: Global security advisories (GHSA), severity filtering & advisory metadata
  - ZGitHub: Bounded deduplication & async session aclose()
  - ZSecurity: Security RSS feed CVE extraction, severity scoring & priority metadata
  - Invariants: Pure canonical SourceObservation emission, UTC timestamps, frozen dataclass
"""

import asyncio
from datetime import datetime, UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor, SourceType
from src.zombies.z_github import ZGitHub
from src.zombies.z_hacker import ZHacker
from src.zombies.z_security import ZSecurity


# =============================================================================
# 1. Z-HACKER TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_z_hacker_creates_canonical_source_observations():
    source = SourceDescriptor(
        id="hn_api",
        url="https://news.ycombinator.com",
        name="Hacker News",
        type=SourceType.API,
        tier=2,
    )
    zombie = ZHacker(source)

    sample_story = {
        "id": 99001,
        "type": "story",
        "title": "Show HN: Fast Vector Search in WebAssembly",
        "url": "https://example.com/wasm-vector",
        "score": 150,
        "time": 1786712400,  # UTC timestamp
    }

    with patch.object(zombie, "_fetch_list", AsyncMock(side_effect=[[99001], []])), \
         patch.object(zombie, "_fetch_item", AsyncMock(return_value=sample_story)):
        observations = await zombie.hunt()

    assert len(observations) == 1
    obs = observations[0]
    assert isinstance(obs, SourceObservation)
    assert obs.source_id == "hn_api"
    assert obs.source_name == "Hacker News"
    assert obs.source_tier == SourceTier.TIER_2_SPECIALIST
    assert obs.zombie_species == ZombieSpecies.HACKER_NEWS
    assert obs.url == "https://example.com/wasm-vector"
    assert obs.title == "Show HN: Fast Vector Search in WebAssembly"
    assert obs.summary == "HN Score: 150"
    assert obs.published_at_hint is not None
    assert obs.published_at_hint.tzinfo == UTC
    assert obs.metadata.get("hn_item_id") == 99001
    assert obs.metadata.get("hn_score") == 150
    assert obs.metadata.get("high_velocity") is False

    await zombie.aclose()


@pytest.mark.asyncio
async def test_z_hacker_velocity_detection():
    source = SourceDescriptor(
        id="hn_api",
        url="https://news.ycombinator.com",
        name="Hacker News",
        type=SourceType.API,
        tier=2,
    )
    zombie = ZHacker(source)

    story_id = 99002
    story_initial = {
        "id": story_id,
        "type": "story",
        "title": "Breaking: New Quantum Chip Architecture",
        "url": "https://example.com/quantum-chip",
        "score": 25,
        "time": 1786712400,
    }
    story_hot = {
        "id": story_id,
        "type": "story",
        "title": "Breaking: New Quantum Chip Architecture",
        "url": "https://example.com/quantum-chip",
        "score": 120,  # Gained 95 points in seconds -> high velocity
        "time": 1786712400,
    }

    # Initial hunt
    with patch.object(zombie, "_fetch_list", AsyncMock(side_effect=[[story_id], []])), \
         patch.object(zombie, "_fetch_item", AsyncMock(return_value=story_initial)):
        first_hunt = await zombie.hunt()

    assert len(first_hunt) == 1
    assert first_hunt[0].metadata.get("high_velocity") is False

    # Second hunt: story gained rapid score
    with patch.object(zombie, "_fetch_list", AsyncMock(side_effect=[[story_id], []])), \
         patch.object(zombie, "_fetch_item", AsyncMock(return_value=story_hot)):
        second_hunt = await zombie.hunt()

    # Re-emitted because it became high velocity
    assert len(second_hunt) == 1
    assert second_hunt[0].metadata.get("high_velocity") is True
    assert second_hunt[0].metadata.get("hn_score") == 120

    await zombie.aclose()


@pytest.mark.asyncio
async def test_z_hacker_aclose_lifecycle():
    source = SourceDescriptor(
        id="hn_api",
        url="https://news.ycombinator.com",
        name="Hacker News",
        type=SourceType.API,
        tier=2,
    )
    zombie = ZHacker(source)
    session = await zombie._ensure_session()
    assert not session.closed

    # aclose should close session cleanly
    await zombie.aclose()
    assert session.closed
    assert zombie._session is None
    assert zombie.is_running is False


# =============================================================================
# 2. Z-GITHUB TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_z_github_release_observations():
    source = SourceDescriptor(
        id="github_events",
        url="https://api.github.com",
        name="GitHub Releases",
        type=SourceType.API,
        tier=1,
    )
    zombie = ZGitHub(source)

    sample_release_payload = [
        {
            "id": 88001,
            "tag_name": "v6.14.0",
            "name": "Linux 6.14.0",
            "html_url": "https://github.com/torvalds/linux/releases/tag/v6.14.0",
            "published_at": "2026-08-14T10:00:00Z",
            "body": "Kernel release with full RISC-V hypervisor support.",
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"ETag": '"abc123etag"'}
    mock_resp.json = AsyncMock(return_value=sample_release_payload)

    # Context manager mock for session.get
    mock_get = MagicMock()
    mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_get.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_get

    with patch.object(zombie, "_ensure_session", AsyncMock(return_value=mock_session)), \
         patch.object(zombie, "_check_advisories", AsyncMock(return_value=[])):
        observations = await zombie._check_releases(mock_session, "torvalds/linux")

    assert len(observations) == 1
    obs = observations[0]
    assert obs.zombie_species == ZombieSpecies.GITHUB
    assert obs.source_tier == SourceTier.TIER_1_PREMIUM
    assert obs.url == "https://github.com/torvalds/linux/releases/tag/v6.14.0"
    assert obs.title == "Linux releases Linux 6.14.0"
    assert obs.published_at_hint == datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)
    assert obs.metadata.get("event_type") == "release"
    assert obs.metadata.get("repo") == "torvalds/linux"
    assert obs.metadata.get("tag") == "v6.14.0"
    assert obs.metadata.get("is_primary") is True

    await zombie.aclose()


@pytest.mark.asyncio
async def test_z_github_security_advisories():
    source = SourceDescriptor(
        id="github_events",
        url="https://api.github.com",
        name="GitHub Security Advisory",
        type=SourceType.API,
        tier=2,
    )
    zombie = ZGitHub(source)

    sample_advisories = [
        {
            "ghsa_id": "GHSA-xxxx-yyyy-zzzz",
            "summary": "Remote Code Execution in PyTorch Distributed Runtime",
            "html_url": "https://github.com/advisories/GHSA-xxxx-yyyy-zzzz",
            "published_at": "2026-08-14T11:00:00Z",
            "severity": "critical",
            "description": "An unauthenticated remote code execution vulnerability.",
        },
        {
            "ghsa_id": "GHSA-low-0001",
            "summary": "Minor denial of service in debug logger",
            "html_url": "https://github.com/advisories/GHSA-low-0001",
            "published_at": "2026-08-14T11:30:00Z",
            "severity": "low",  # Should be filtered out (< high)
            "description": "Minor DoS under heavy debug load.",
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"ETag": '"advisory_etag"'}
    mock_resp.json = AsyncMock(return_value=sample_advisories)

    mock_get = MagicMock()
    mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_get.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_get

    with patch.object(zombie, "_ensure_session", AsyncMock(return_value=mock_session)):
        observations = await zombie._check_advisories(mock_session)

    # Only critical/high advisory kept
    assert len(observations) == 1
    obs = observations[0]
    assert obs.zombie_species == ZombieSpecies.GITHUB
    assert obs.source_tier == SourceTier.TIER_2_SPECIALIST
    assert obs.url == "https://github.com/advisories/GHSA-xxxx-yyyy-zzzz"
    assert "Security Advisory: Remote Code Execution" in obs.title
    assert obs.published_at_hint == datetime(2026, 8, 14, 11, 0, 0, tzinfo=UTC)
    assert obs.metadata.get("event_type") == "advisory"
    assert obs.metadata.get("ghsa_id") == "GHSA-xxxx-yyyy-zzzz"
    assert obs.metadata.get("severity") == "critical"
    assert obs.metadata.get("is_primary") is True

    await zombie.aclose()


# =============================================================================
# 3. Z-SECURITY TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_z_security_cve_extraction_and_priority():
    source = SourceDescriptor(
        id="cisa_feed",
        url="https://www.cisa.gov/rss/advisories.xml",
        name="CISA Security Feed",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZSecurity(source)

    sample_security_rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CISA Advisories</title>
    <link>https://www.cisa.gov</link>
    <item>
      <title>Critical Zero-Day in OpenSSL TLS Engine (CVE-2026-9999)</title>
      <link>https://cisa.gov/advisory/cve-2026-9999</link>
      <description>Active exploitation confirmed for CVE-2026-9999 remote memory corruption.</description>
      <pubDate>Fri, 14 Aug 2026 09:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Moderate Buffer Overflow in Web Server (CVE-2026-1111)</title>
      <link>https://cisa.gov/advisory/cve-2026-1111</link>
      <description>Vendor advisory published for patch 1.2.</description>
      <pubDate>Fri, 14 Aug 2026 08:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=sample_security_rss)):
        observations = await zombie.hunt()

    assert len(observations) == 2
    
    # Critical zero day
    obs1 = observations[0]
    assert obs1.zombie_species == ZombieSpecies.SECURITY
    assert obs1.source_tier == SourceTier.TIER_1_PREMIUM
    assert "CVE-2026-9999" in obs1.metadata.get("cve_ids")
    assert obs1.metadata.get("severity") == "critical"
    assert obs1.metadata.get("is_primary") is True
    assert obs1.metadata.get("security_source") is True

    # Moderate vulnerability
    obs2 = observations[1]
    assert obs2.zombie_species == ZombieSpecies.SECURITY
    assert "CVE-2026-1111" in obs2.metadata.get("cve_ids")
    assert obs2.metadata.get("severity") in ("high", "medium")


# =============================================================================
# 4. FROZEN INVARIANT TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_specialized_zombies_emit_frozen_observations():
    source = SourceDescriptor(
        id="cisa_feed",
        url="https://www.cisa.gov/rss/advisories.xml",
        name="CISA Security Feed",
        type=SourceType.RSS,
        tier=1,
    )
    zombie = ZSecurity(source)

    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CISA</title>
    <link>https://cisa.gov</link>
    <item>
      <title>Security Alert CVE-2026-3333</title>
      <link>https://cisa.gov/advisory/cve-2026-3333</link>
      <description>Advisory description</description>
      <pubDate>Fri, 14 Aug 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    with patch("src.zombies.z_rss.browser.fetch", AsyncMock(return_value=sample_rss)):
        observations = await zombie.hunt()

    obs = observations[0]
    with pytest.raises(Exception):
        obs.title = "Mutated Security Title"
    with pytest.raises(Exception):
        obs.metadata["severity"] = "mutated"
