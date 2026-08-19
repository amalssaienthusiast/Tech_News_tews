"""
Centralized Source Registry for Tech News Scraper.

Provides a single source of truth for all news sources (built-in, custom, API).
Displaces fragmented source loading across primp_crawler, realtime_feeder, enhanced_feeder, and orchestrator.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from typing import Dict, List, Optional, Any

import aiohttp

logger = logging.getLogger(__name__)

CUSTOM_SOURCES_FILE = Path("data/custom_sources.json")

class SourceType(str, Enum):
    RSS = "rss"
    HTML = "html"        # Homepage / listing page requiring CSS/heuristic extraction
    API = "api"         # Official API client (Google News, Bing, NewsAPI, Reddit, etc.)

@dataclass
class SourceDescriptor:
    id: str                                  # Stable hash of URL
    url: str
    name: str
    type: SourceType
    tier: int = 3                             # 1=curated built-in, 2=API, 3=custom
    link_selector: Optional[str] = None      # For HTML type
    delay_seconds: float = 30.0               # Per-source pacing interval
    # Scheduler and bypass state
    last_attempt: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_working_tier: int = 0                # BypassResolver tier that worked last time
    consecutive_failures: int = 0
    cooldown_until: Optional[datetime] = None
    is_blacklisted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "type": self.type.value,
            "tier": self.tier,
            "link_selector": self.link_selector,
            "delay_seconds": self.delay_seconds,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_working_tier": self.last_working_tier,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "is_blacklisted": self.is_blacklisted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceDescriptor":
        return cls(
            id=data["id"],
            url=data["url"],
            name=data["name"],
            type=SourceType(data.get("type", "rss")),
            tier=data.get("tier", 3),
            link_selector=data.get("link_selector"),
            delay_seconds=data.get("delay_seconds", 30.0),
            last_attempt=datetime.fromisoformat(data["last_attempt"]) if data.get("last_attempt") else None,
            last_success=datetime.fromisoformat(data["last_success"]) if data.get("last_success") else None,
            last_working_tier=data.get("last_working_tier", 0),
            consecutive_failures=data.get("consecutive_failures", 0),
            cooldown_until=datetime.fromisoformat(data["cooldown_until"]) if data.get("cooldown_until") else None,
            is_blacklisted=data.get("is_blacklisted", False),
        )

    def to_source_health(self) -> Any:
        """Convert SourceDescriptor to canonical SourceHealth domain model."""
        from src.domain.enums import SourceHealthStatus
        from src.domain.models import SourceHealth

        now = datetime.now(UTC)
        if self.is_blacklisted:
            status = SourceHealthStatus.QUARANTINED if (self.cooldown_until and self.cooldown_until > now) else SourceHealthStatus.DEAD
        elif self.cooldown_until and self.cooldown_until > now:
            if self.consecutive_failures >= 5:
                status = SourceHealthStatus.COOLDOWN
            else:
                status = SourceHealthStatus.RATE_LIMITED
        elif self.consecutive_failures > 0:
            status = SourceHealthStatus.DEGRADED
        else:
            status = SourceHealthStatus.HEALTHY

        return SourceHealth(
            source_id=self.id,
            source_url=self.url,
            source_name=self.name,
            status=status,
            consecutive_failures=self.consecutive_failures,
            consecutive_successes=0 if self.consecutive_failures > 0 else 1,
            last_attempt=self.last_attempt,
            last_success=self.last_success,
            last_status_code=None,
            cooldown_until=self.cooldown_until,
            rate_limit_reset_at=self.cooldown_until if status == SourceHealthStatus.RATE_LIMITED else None,
            working_bypass_tier=self.last_working_tier,
        )

    def apply_source_health(self, health: Any) -> None:
        """Apply canonical SourceHealth domain state to this SourceDescriptor."""
        from src.domain.enums import SourceHealthStatus
        self.consecutive_failures = health.consecutive_failures
        self.last_attempt = health.last_attempt
        self.last_success = health.last_success
        self.cooldown_until = health.cooldown_until
        self.last_working_tier = health.working_bypass_tier
        self.is_blacklisted = (health.status in (SourceHealthStatus.DEAD, SourceHealthStatus.QUARANTINED))


def make_source_id(url: str) -> str:
    """Generate a stable 16-character MD5 hash for a URL."""
    return hashlib.md5(url.strip().lower().encode("utf-8")).hexdigest()[:16]


class SourceRegistry:
    """
    Single source of truth registry managing source descriptors, type probing,
    and failure backoff states.
    """

    DEFAULT_TARGET_SITES: List[Dict[str, Any]] = [
        {"name": "Hacker News", "url": "https://news.ycombinator.com/rss", "type": "rss", "tier": 1, "delay_seconds": 15.0},
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "type": "rss", "tier": 1, "delay_seconds": 30.0},
        {"name": "Ars Technica", "url": "http://feeds.arstechnica.com/arstechnica/index", "type": "rss", "tier": 1, "delay_seconds": 45.0},
        {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "type": "rss", "tier": 1, "delay_seconds": 45.0},
        {"name": "Wired", "url": "https://www.wired.com/feed/rss", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "The Register", "url": "https://www.theregister.com/headlines.atom", "type": "rss", "tier": 1, "delay_seconds": 45.0},
        {"name": "9to5Mac", "url": "https://9to5mac.com/feed/", "type": "rss", "tier": 1, "delay_seconds": 45.0},
        {"name": "Engadget", "url": "https://www.engadget.com/rss.xml", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "VentureBeat", "url": "https://venturebeat.com/feed/", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "ZDNet", "url": "https://www.zdnet.com/news/rss.xml", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "Slashdot", "url": "http://rss.slashdot.org/Slashdot/slashdotMain", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "IEEE Spectrum", "url": "https://spectrum.ieee.org/feeds/feed.rss", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "Android Authority", "url": "https://www.androidauthority.com/feed/", "type": "rss", "tier": 1, "delay_seconds": 60.0},
        {"name": "Tom's Hardware", "url": "https://www.tomshardware.com/feeds/all", "type": "rss", "tier": 1, "delay_seconds": 60.0},
    ]

    def __init__(self, storage_path: Path = CUSTOM_SOURCES_FILE):
        self._storage_path = storage_path
        self._sources: Dict[str, SourceDescriptor] = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load built-in and persisted custom sources into memory."""
        with self._lock:
            self._sources.clear()

            # Load built-in defaults
            for site in self.DEFAULT_TARGET_SITES:
                sid = make_source_id(site["url"])
                desc = SourceDescriptor(
                    id=sid,
                    url=site["url"],
                    name=site["name"],
                    type=SourceType(site["type"]),
                    tier=site["tier"],
                    delay_seconds=site.get("delay_seconds", 30.0)
                )
                self._sources[sid] = desc

            # Load persisted custom sources
            if self._storage_path.exists():
                try:
                    with open(self._storage_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for item in data.get("sources", []):
                            desc = SourceDescriptor.from_dict(item)
                            self._sources[desc.id] = desc
                    logger.info(f"Loaded {len(self._sources)} sources from registry storage.")
                except Exception as e:
                    logger.error(f"Error loading custom sources from {self._storage_path}: {e}")

    def save(self) -> None:
        """Atomically persist custom and state-updated sources to disk."""
        with self._lock:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            custom_items = [desc.to_dict() for desc in self._sources.values() if desc.tier >= 2 or desc.consecutive_failures > 0]
            data = {"sources": custom_items}
            temp_path = self._storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self._storage_path)

    def get_all_ordered(self) -> List[SourceDescriptor]:
        """Return all registered sources in stable deterministic order."""
        with self._lock:
            return sorted(self._sources.values(), key=lambda s: (s.tier, s.name))

    def get_source(self, source_id: str) -> Optional[SourceDescriptor]:
        with self._lock:
            return self._sources.get(source_id)

    async def probe_source_type(self, url: str) -> SourceType:
        """
        Lightweight probe to determine if URL is RSS/Atom feed or HTML page.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8), headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "xml" in content_type or "rss" in content_type or "atom" in content_type:
                        return SourceType.RSS
                    text_sample = await resp.text()
                    text_sample_lower = text_sample[:1024].lower()
                    if "<rss" in text_sample_lower or "<feed" in text_sample_lower or "xml" in text_sample_lower:
                        return SourceType.RSS
        except Exception as e:
            logger.debug(f"Source type probe failed for {url}: {e}")
        
        # Default fallback: check URL extension
        if url.endswith(".xml") or url.endswith(".rss") or "feed" in url.lower():
            return SourceType.RSS
        return SourceType.HTML

    async def add_custom(self, url: str, name: Optional[str] = None, source_type: Optional[SourceType] = None, delay_seconds: float = 30.0) -> SourceDescriptor:
        """Atomic source registration with automatic probing."""
        sid = make_source_id(url)

        if not source_type:
            source_type = await self.probe_source_type(url)

        source_name = name or url.split("//")[-1].split("/")[0]
        desc = SourceDescriptor(
            id=sid,
            url=url,
            name=source_name,
            type=source_type,
            tier=3,
            delay_seconds=delay_seconds
        )

        with self._lock:
            self._sources[sid] = desc
        
        self.save()
        logger.info(f"Added custom source to registry: {source_name} ({url}) as {source_type.value}")
        return desc

    def remove_custom(self, source_id: str) -> bool:
        """Remove source by ID."""
        with self._lock:
            if source_id in self._sources:
                del self._sources[source_id]
                self.save()
                return True
            return False

    def record_result(self, source_id: str, success: bool, tier_used: int = 0, article_count: int = 0, status_code: Optional[int] = None) -> None:
        """
        Record result of a scrape attempt. Updates consecutive_failures, cooldown_until, and blacklisting.
        HTTP 404 (Not Found) or 410 (Gone) automatically blacklists/quarantines the source for 7 days.
        """
        now = datetime.now(UTC)
        with self._lock:
            desc = self._sources.get(source_id)
            if not desc:
                return

            desc.last_attempt = now

            if success:
                desc.last_success = now
                desc.last_working_tier = tier_used
                desc.consecutive_failures = 0
                desc.cooldown_until = None
                desc.is_blacklisted = False
            else:
                desc.consecutive_failures += 1
                if status_code in (404, 410):
                    desc.is_blacklisted = True
                    desc.cooldown_until = now + timedelta(days=7)
                    logger.warning(f"Source {desc.name} ({desc.url}) returned HTTP {status_code}. Blacklisted & quarantined for 7 days.")
                elif desc.consecutive_failures >= 5:
                    # Exponential backoff: 2^(fails - 5) minutes, capped at 6 hours
                    backoff_minutes = min(360, 2 ** (desc.consecutive_failures - 5) * 5)
                    desc.cooldown_until = now + timedelta(minutes=backoff_minutes)
                    logger.warning(f"Source {desc.name} has {desc.consecutive_failures} failures. Cooldown until {desc.cooldown_until.isoformat()}")

        self.save()
