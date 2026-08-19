"""
Z-WEB — Web HTML Zombie Species.

Hunts on HTML pages (like homepages). Uses the InternetBrowser to bypass
WAFs, extracts headlines using CSS selectors or heuristic extraction,
and enforces minimum title length rules.
"""

from collections import OrderedDict
import logging
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor
from src.utils.text import sanitize_title
from .internet_browser import browser
from .zombie_base import ZombieBase

logger = logging.getLogger(__name__)


class ZWeb(ZombieBase):
    """HTML webpage hunting zombie."""
    
    species = ZombieSpecies.WEB

    def __init__(self, source: SourceDescriptor):
        super().__init__(source)
        # Bounded seen URLs index (FIFO eviction over 500 entries)
        self._seen_urls: OrderedDict[str, bool] = OrderedDict()

    def _resolve_tier(self) -> SourceTier:
        """Resolve SourceTier from source descriptor tier."""
        if self.source.tier == 1:
            return SourceTier.TIER_1_PREMIUM
        elif self.source.tier == 2:
            return SourceTier.TIER_2_SPECIALIST
        elif self.source.tier == 3:
            return SourceTier.TIER_3_COMMUNITY
        return SourceTier.TIER_4_DISCOVERY

    async def hunt(self) -> List[SourceObservation]:
        """Fetch HTML page and extract headlines as canonical SourceObservations."""
        # For Z-WEB, we often need tier 1 (primp) or higher to bypass Cloudflare
        content = await browser.fetch(self.source)
        if not content:
            return []

        # WAF challenge check (just in case the browser tier thought it succeeded)
        if "Just a moment..." in content or "cf-browser-verification" in content:
            logger.warning(f"🧟 {self.name} hit a WAF block despite bypass.")
            return []

        new_sources: List[SourceObservation] = []
        soup = BeautifulSoup(content, "html.parser")

        # Strip junk that often contains navigation links
        for junk_el in soup.find_all(["nav", "footer", "header", "aside", "script", "style", "noscript"]):
            junk_el.decompose()

        # Get selector or fallback
        selector = self.source.link_selector
        if not selector:
            selector = "article a, h2 a, h3 a, .title a, a.title, .headline a, .post-title a, .story a"
            
        links = soup.select(selector)
        
        # Heuristic fallback if standard selectors yield nothing (e.g. for custom sources)
        if not links:
            all_links = soup.find_all("a")
            for a in all_links:
                text = a.get_text(strip=True)
                if len(text) > 20 and len(text) < 150 and len(text.split()) > 3:
                    links.append(a)

        tier = self._resolve_tier()

        # Process top links
        for link in links[:30]:
            href = link.get("href")
            raw_title = link.get_text(strip=True)
            clean_title = sanitize_title(raw_title)
            
            if not href or not clean_title:
                continue

            # Ensure it's a real headline (5+ words)
            title_words = [w for w in clean_title.split() if len(w) > 1]
            if len(title_words) < 5:
                continue
                
            # Reject garbled or navigation text
            if clean_title.startswith("[") or clean_title.startswith("{"):
                continue
            lower_title = clean_title.lower()
            if any(lower_title.startswith(p) for p in ("view more", "read more", "see all", "load more")):
                continue

            full_url = urljoin(self.source.url, href)
            
            if full_url in self._seen_urls:
                continue

            source_obs = SourceObservation.create(
                source_id=self.source.id,
                source_name=self.source.name,
                source_tier=tier,
                zombie_species=self.species,
                url=full_url,
                title=clean_title,
                raw_content="",
                summary="",
                published_at_hint=None,
            )
            
            new_sources.append(source_obs)
            self._seen_urls[full_url] = True
            
            # Keep seen_urls bounded to 500 items (FIFO eviction)
            if len(self._seen_urls) > 500:
                self._seen_urls.popitem(last=False)

        return new_sources
