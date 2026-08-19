"""
Z-RSS — RSS/Atom Zombie Species.

Hunts on traditional XML feeds. Uses the InternetBrowser to bypass protections.
Adapts polling frequency based on how often the feed updates.
"""

from collections import OrderedDict
from datetime import datetime, UTC
import email.utils
import logging
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
import feedparser

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor
from src.utils.text import sanitize_title
from .internet_browser import browser
from .zombie_base import ZombieBase

logger = logging.getLogger(__name__)


class ZRss(ZombieBase):
    """RSS feed hunting zombie."""
    
    species = ZombieSpecies.RSS

    def __init__(self, source: SourceDescriptor):
        super().__init__(source)
        # Bounded seen URLs index (FIFO eviction over 500 entries)
        self._seen_urls: OrderedDict[str, bool] = OrderedDict()

    def _resolve_tier(self) -> SourceTier:
        """Resolve SourceTier from source descriptor tier."""
        if self.source.tier <= 1:
            return SourceTier.TIER_1_PREMIUM
        elif self.source.tier == 2:
            return SourceTier.TIER_2_SPECIALIST
        elif self.source.tier == 3:
            return SourceTier.TIER_3_COMMUNITY
        return SourceTier.TIER_4_DISCOVERY

    def _build_metadata(self, entry: Any) -> Optional[Dict[str, Any]]:
        """Hook for subclasses to attach specific domain metadata."""
        return None

    async def hunt(self) -> List[SourceObservation]:
        """Fetch RSS feed and extract new articles as canonical SourceObservations."""
        content = await browser.fetch(self.source)
        if not content:
            return []

        # Parse RSS / Atom
        feed = feedparser.parse(content)
        new_sources: List[SourceObservation] = []

        # Only process up to 25 items to keep it fast
        for entry in feed.entries[:25]:
            url = getattr(entry, "link", None)
            if not url or url in self._seen_urls:
                continue
                
            title = getattr(entry, "title", None)
            clean_title = sanitize_title(title)
            if not clean_title:
                continue

            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")

            # Date parsing (strictly timezone-aware UTC)
            pub_date = self._parse_date(entry)
            image_url = self._extract_image(entry, summary)

            tier = self._resolve_tier()
            metadata = self._build_metadata(entry)

            source_obs = SourceObservation.create(
                source_id=self.source.id,
                source_name=self.source.name,
                source_tier=tier,
                zombie_species=self.species,
                url=url,
                title=clean_title,
                raw_content="",
                summary=summary.strip()[:500],
                image_url=image_url,
                published_at_hint=pub_date,
                metadata=metadata,
            )
            
            new_sources.append(source_obs)
            self._seen_urls[url] = True
            
            # Keep seen_urls bounded to 500 items (FIFO eviction)
            if len(self._seen_urls) > 500:
                self._seen_urls.popitem(last=False)

        return new_sources

    def _parse_date(self, entry: Any) -> Optional[datetime]:
        """Robust date parsing for RSS/Atom guaranteeing timezone-aware UTC datetime."""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6], tzinfo=UTC)
            except Exception:
                pass
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6], tzinfo=UTC)
            except Exception:
                pass

        # String parsing fallbacks
        for attr in ("published", "updated", "created", "pubDate"):
            val = getattr(entry, attr, None)
            if val and isinstance(val, str):
                try:
                    val_clean = val.strip()
                    if val_clean.endswith("Z"):
                        val_clean = val_clean[:-1] + "+00:00"
                    dt = datetime.fromisoformat(val_clean)
                    if dt.tzinfo is None:
                        return dt.replace(tzinfo=UTC)
                    return dt.astimezone(UTC)
                except Exception:
                    pass
                try:
                    dt = email.utils.parsedate_to_datetime(val)
                    if dt:
                        if dt.tzinfo is None:
                            return dt.replace(tzinfo=UTC)
                        return dt.astimezone(UTC)
                except Exception:
                    pass
        return None

    def _extract_image(self, entry: Any, summary: str) -> Optional[str]:
        """Extract article thumbnail image URL."""
        media_content = getattr(entry, "media_content", None)
        if media_content and isinstance(media_content, list):
            for item in media_content:
                if isinstance(item, dict) and item.get("url"):
                    if item.get("medium") == "image" or item.get("type", "").startswith("image/") or not item.get("type"):
                        return item["url"]

        media_thumbnail = getattr(entry, "media_thumbnail", None)
        if media_thumbnail and isinstance(media_thumbnail, list):
            for item in media_thumbnail:
                if isinstance(item, dict) and item.get("url"):
                    return item["url"]

        if "<img" in summary.lower():
            try:
                soup = BeautifulSoup(summary, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if src and src.startswith("http") and not any(skip in src.lower() for skip in ["tracker", "pixel"]):
                        return src
            except Exception:
                pass
        return None
