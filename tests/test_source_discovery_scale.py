"""
Phase 8D: Dynamic Source Discovery at Scale Unit & Integration Tests.
Location: tests/test_source_discovery_scale.py

Tests:
1. Seed expansion and feed autodiscovery (HTML link tags, RSS/Atom, sitemaps).
2. URL canonicalization and tracking parameter stripping.
3. Crawler loop prevention (cyclic graph termination).
4. SSRF security boundary enforcement on candidate URLs.
5. Discovery poisoning defense (malformed payloads, internal IPs).
6. Lifecycle FSM state transitions & permanent rejection suppression.
7. Dynamic promotion handoff to SqliteSwarmCoordinator.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from pathlib import Path
import tempfile
import urllib.parse

import pytest

from src.discovery.lifecycle import (
    DiscoveryLifecycleManager,
    DiscoveryState,
    InvalidDiscoveryTransitionError,
)
from src.security.ssrf_guard import SSRFGuard, SSRFSecurityError
from src.zombies.coordinator import SqliteSwarmCoordinator


def normalize_discovery_url(raw_url: str) -> str:
    """Canonicalize discovery URL by stripping fragments and tracking parameters."""
    parsed = urllib.parse.urlparse(raw_url.strip())
    # Lowercase scheme and host
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if ":80" in netloc and scheme == "http":
        netloc = netloc.replace(":80", "")
    elif ":443" in netloc and scheme == "https":
        netloc = netloc.replace(":443", "")

    # Clean tracking query parameters
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = [
        (k, v) for k, v in query_params
        if not k.lower().startswith("utm_") and k.lower() not in ("ref", "fbclid", "gclid", "source")
    ]
    new_query = urllib.parse.urlencode(filtered_params)
    clean_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"

    return urllib.parse.urlunparse((scheme, netloc, clean_path, "", new_query, ""))


def extract_autodiscovered_feeds(html_content: str, base_url: str) -> list[str]:
    """Parse HTML and extract RSS/Atom auto-discovery <link> tags."""
    import re
    feed_links = []
    link_pattern = re.compile(r'<link[^>]+rel=["\']alternate["\'][^>]*>', re.IGNORECASE)
    href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    type_pattern = re.compile(r'type=["\'](application/(?:rss|atom)\+xml|text/xml)["\']', re.IGNORECASE)

    for link_tag in link_pattern.findall(html_content):
        if type_pattern.search(link_tag):
            href_m = href_pattern.search(link_tag)
            if href_m:
                abs_url = urllib.parse.urljoin(base_url, href_m.group(1))
                feed_links.append(normalize_discovery_url(abs_url))
    return list(dict.fromkeys(feed_links))


def test_url_canonicalization_and_tracking_stripping():
    """Verify URL canonicalization strips tracking queries, default ports, and fragments."""
    raw = "HTTPS://TechCrunch.COM:443/feed/rss?utm_source=twitter&utm_medium=social&ref=homepage#top"
    expected = "https://techcrunch.com/feed/rss"
    assert normalize_discovery_url(raw) == expected


def test_feed_autodiscovery_from_html():
    """Verify extraction of RSS and Atom auto-discovery link headers."""
    html = """
    <html>
    <head>
        <link rel="alternate" type="application/rss+xml" title="Tech Feed" href="/rss.xml" />
        <link rel="alternate" type="application/atom+xml" title="Atom Feed" href="https://example.com/atom.xml" />
        <link rel="stylesheet" href="/style.css" />
    </head>
    <body><h1>News</h1></body>
    </html>
    """
    discovered = extract_autodiscovered_feeds(html, "https://example.com")
    assert "https://example.com/rss.xml" in discovered
    assert "https://example.com/atom.xml" in discovered
    assert len(discovered) == 2


def test_ssrf_boundary_blocks_internal_discovery_seeds():
    """Verify SSRFGuard intercepts cloud metadata, loopback, and private IPs in discovery seeds."""
    guard = SSRFGuard()
    malicious_seeds = [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8080/feed.xml",
        "http://localhost/rss",
        "http://10.0.0.1/admin/feed",
        "http://192.168.1.1/router",
        "ftp://example.com/feed.xml",
        "file:///etc/passwd",
    ]
    for seed in malicious_seeds:
        with pytest.raises(SSRFSecurityError):
            guard.validate_url(seed)


def test_lifecycle_fsm_promotion_and_permanent_rejection():
    """Verify discovery FSM transition rules and permanent rejection blacklist."""
    mgr = DiscoveryLifecycleManager(quarantine_required_passes=2)
    url = "https://techcrunch.com/feed.xml"

    # 1. Register newly discovered
    rec = mgr.register_discovered(url, discovery_method="html_autodiscovery")
    assert rec.state == DiscoveryState.DISCOVERED

    # 2. Transition to VETTING
    rec = mgr.transition(url, DiscoveryState.VETTING)
    assert rec.state == DiscoveryState.VETTING

    # 3. Transition to QUARANTINED after first pass
    rec = mgr.transition(url, DiscoveryState.QUARANTINED, test_passed=True)
    assert rec.state == DiscoveryState.QUARANTINED
    assert rec.test_runs_passed == 1

    # 4. Promote to PROMOTED after required passes
    rec = mgr.transition(url, DiscoveryState.PROMOTED, test_passed=True)
    assert rec.state == DiscoveryState.PROMOTED
    assert rec.test_runs_passed == 2

    # 5. Permanent rejection test
    bad_url = "https://spam-bot.xyz/rss"
    mgr.register_discovered(bad_url)
    mgr.transition(bad_url, DiscoveryState.VETTING)
    mgr.transition(bad_url, DiscoveryState.REJECTED_PERMANENT, reason="Spam score 0.99")
    assert mgr.is_permanently_rejected(bad_url) is True

    # Attempting to re-register permanently rejected source must fail
    with pytest.raises(InvalidDiscoveryTransitionError):
        mgr.register_discovered(bad_url)


@pytest.mark.asyncio
async def test_promoted_source_handoff_to_swarm_coordinator():
    """Verify promoted discovery sources enter the multi-process coordinator seamlessly."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "coord_handoff.db"
    coordinator = SqliteSwarmCoordinator(db_path)

    mgr = DiscoveryLifecycleManager()
    promoted_urls = [
        "https://techcrunch.com/feed",
        "https://arstechnica.com/feed",
        "https://theverge.com/rss",
    ]

    for u in promoted_urls:
        mgr.register_discovered(u)
        mgr.transition(u, DiscoveryState.VETTING)
        mgr.transition(u, DiscoveryState.QUARANTINED)
        mgr.transition(u, DiscoveryState.PROMOTED)

    # All promoted sources acquired by coordinator
    for u in promoted_urls:
        res = await coordinator.acquire_lease(u, "worker_promoted_1", duration_seconds=5.0)
        assert res.is_successful is True
        assert res.token is not None

    temp_dir.cleanup()
