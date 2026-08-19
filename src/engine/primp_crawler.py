"""
Primp-based Real-time Crawler for Tech News Scrapper.

Utilizes `primp` to impersonate advanced browsers (e.g. chrome_120) and bypass Cloudflare/WAF 
protections (e.g., HTTP 202 from Ars Technica) without fully relying on Playwright.
Directly parses the homepage of major tech news sites to extract the latest headlines.
"""

import asyncio
import logging
import hashlib
from datetime import datetime, UTC
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from src.core.types import Article, SourceTier
from src.sources.custom_source_loader import CustomSourceManager
from src.utils.text import sanitize_title

logger = logging.getLogger(__name__)

class PrimpRealtimeCrawler:
    """Crawler that leverages primp to bypass WAFs and fetch realtime news."""
    
    TARGET_SITES = [
        {"name": "Ars Technica", "url": "https://arstechnica.com/", "link_selector": "h2 > a"},
        {"name": "The Verge", "url": "https://www.theverge.com/tech", "link_selector": "h2 a"},
        {"name": "TechCrunch", "url": "https://techcrunch.com/", "link_selector": "h2.wp-block-post-title a"},
        {"name": "Wired", "url": "https://www.wired.com/", "link_selector": "h3.SummaryItemHedBase-hiFYom a"},
        {"name": "Hacker News", "url": "https://news.ycombinator.com/", "link_selector": "span.titleline > a"}
    ]

    def __init__(self, impersonate: Optional[str] = None):
        if impersonate is None:
            try:
                from src.utils.primp_profiles import get_chrome_profile
                impersonate = get_chrome_profile()
            except ImportError:
                impersonate = "chrome_133"
        self.impersonate = impersonate
        self.client = None

    def _init_client(self):
        if self.client is None:
            try:
                import primp
                self.client = primp.Client(impersonate=self.impersonate, follow_redirects=True)
            except ImportError:
                logger.error("primp library is not installed. Crawler will fail.")

    async def fetch_realtime_news(self, limit_per_site: int = 15) -> List[Article]:
        """Deprecated standalone loop - routes directly to Unified Feed Chain Engine."""
        from src.engine.unified_chain import unified_engine
        await unified_engine.start()
        return unified_engine.get_articles(count=limit_per_site * len(self.TARGET_SITES))

    async def _scrape_site(self, site: dict, limit: int) -> List[Article]:
        """Scrape a specific site for headlines using primp."""
        url = site["url"]
        logger.info(f"🕸️ Primp Crawler fetching: {url}")
        
        loop = asyncio.get_event_loop()
        
        def _fetch():
            try:
                from src.utils.primp_profiles import safe_primp_get
                response = safe_primp_get(url, impersonate=self.impersonate, timeout=30.0)
                if response and response.status_code in (200, 202):
                    return response.text
                elif response:
                    logger.warning(f"Primp returned HTTP {response.status_code} for {url}")
                    return None
                return None
            except Exception as e:
                logger.warning(f"Primp failed to fetch {url}: {e}")
                return None


        html = await loop.run_in_executor(None, _fetch)
        if not html:
            return []

        return self._extract_articles(html, site, limit)

    def _extract_articles(self, html: str, site: dict, limit: int) -> List[Article]:
        """Parse HTML to extract Articles."""
        articles = []
        soup = BeautifulSoup(html, "html.parser")
        
        # If Ars Technica 202 Challenge Page is detected
        if "Just a moment..." in soup.text or "Cloudflare" in soup.text:
            logger.warning(f"⚠️ {site['name']} returned a Cloudflare Challenge block.")
            # We cannot parse the challenge page for news.
            return []

        # Find links using the selector
        links = soup.select(site["link_selector"])
        
        # If generic selector was used and yielded nothing, fallback to heuristic extraction
        if not links and "Custom" in site["name"]:
            all_links = soup.find_all("a")
            for a in all_links:
                text = a.get_text(strip=True)
                # Heuristic: Headline is usually > 20 chars, < 150 chars, and has multiple words
                if len(text) > 20 and len(text) < 150 and len(text.split()) > 3:
                    links.append(a)
        
        for link in links[:limit]:
            href = link.get("href")
            raw_title = link.get_text(strip=True)
            clean_title = sanitize_title(raw_title)

            if not href or not clean_title:
                continue

            full_url = urljoin(site["url"], href)
            article_id = hashlib.md5(full_url.encode()).hexdigest()

            articles.append(Article(
                id=article_id,
                url=full_url,
                title=clean_title,
                summary="",
                source=site["name"], source_tier=SourceTier.TIER_3,
                published_at=None,  # Don't fabricate dates — let quality filter handle undated articles
                content="",
            ))
            
        logger.info(f"✓ Primp extracted {len(articles)} real-time headlines from {site['name']}")
        return articles
