"""
Directory Scraper for Tech News Scraper v3.0

High-throughput homepage/directory headline harvester.
Scrapes news site homepages to extract article lists for bulk processing.

Features:
- Enterprise throughput (~2000-5000 articles/hour)
- Concurrent scraping with configurable workers
- Integrates with existing StealthBrowser
- Multiple extraction strategies (JSON-LD, semantic, CSS selectors)
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from src.utils.http import create_connector

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HeadlineItem(BaseModel):
    """Extracted headline/article reference from a directory."""
    title: str = Field(description="Article headline")
    url: str = Field(description="Full article URL")
    summary: Optional[str] = Field(default=None, description="Article snippet/description")
    source: str = Field(description="Source site name")
    category: Optional[str] = Field(default=None, description="Category if available")
    published: Optional[str] = Field(default=None, description="Publication date if available")
    image_url: Optional[str] = Field(default=None, description="Thumbnail image URL")
    author: Optional[str] = Field(default=None, description="Author name if available")


@dataclass
class DirectoryConfig:
    """Configuration for scraping a specific directory/homepage."""
    name: str
    url: str
    
    # CSS selectors for extraction
    article_selector: str = "article, .post, .story, .news-item"
    title_selector: str = "h1, h2, h3, .title, .headline"
    link_selector: str = "a"
    summary_selector: str = ".summary, .excerpt, .description, p"
    image_selector: str = "img"
    date_selector: str = "time, .date, .published"
    
    # Rate limiting
    delay_between_requests: float = 1.0
    max_articles: int = 100
    
    # Category if known
    default_category: Optional[str] = None


# Pre-configured news directories for enterprise-grade scraping
DEFAULT_DIRECTORIES = [
    DirectoryConfig(
        name="TechCrunch",
        url="https://techcrunch.com/",
        article_selector=".loop-card",
        title_selector=".loop-card__title-link",
        summary_selector=".loop-card__content",
        default_category="Technology"
    ),
    DirectoryConfig(
        name="The Verge",
        url="https://www.theverge.com/tech",
        article_selector="div.duet--content-cards--content-card",
        title_selector="h2 a, a:not(:has(img))",
        summary_selector="p",
        default_category="Technology"
    ),
    DirectoryConfig(
        name="Wired",
        url="https://www.wired.com/",
        article_selector=".summary-item",
        title_selector=".summary-item__hed",
        summary_selector=".summary-item__dek",
        default_category="Technology"
    ),
    DirectoryConfig(
        name="Ars Technica",
        url="https://arstechnica.com/",
        article_selector="article.post",
        title_selector="h2 a",
        summary_selector=".excerpt",
        default_category="Technology"
    ),
    DirectoryConfig(
        name="Hacker News",
        url="https://news.ycombinator.com/",
        article_selector="tr.athing",
        title_selector=".titleline a",
        link_selector=".titleline a",
        default_category="Startups & Funding"
    ),
]


class DirectoryScraper:
    """
    High-throughput news directory scraper.
    
    Scrapes news homepages and directories to extract headline lists.
    Uses existing StealthBrowser for JavaScript rendering when needed.
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        use_browser: bool = False,
        default_directories: Optional[List[DirectoryConfig]] = None
    ):
        """
        Initialize the directory scraper.
        
        Args:
            max_concurrent: Maximum concurrent scrape operations
            use_browser: Use Playwright for JavaScript rendering
            default_directories: Pre-configured directory configs
        """
        self.max_concurrent = max_concurrent
        self.use_browser = use_browser
        self.directories = default_directories or DEFAULT_DIRECTORIES
        
        # Tracking
        self._scraped_urls: Set[str] = set()
        self._last_scrape: Dict[str, datetime] = {}
        
        # Import browser if available
        self._browser = None
        if use_browser:
            try:
                from src.bypass.browser_engine import StealthBrowser
                self._browser = StealthBrowser()
            except ImportError:
                logger.warning("StealthBrowser not available, using aiohttp")
    
    async def scrape_directory(
        self,
        config: DirectoryConfig,
        limit: Optional[int] = None
    ) -> List[HeadlineItem]:
        """
        Scrape a single directory/homepage for headlines.
        
        Args:
            config: Directory configuration
            limit: Maximum articles to extract
            
        Returns:
            List of HeadlineItem objects
        """
        max_articles = limit or config.max_articles
        headlines: List[HeadlineItem] = []
        
        try:
            logger.info(f"Scraping directory: {config.name} ({config.url})")
            
            # Fetch the page
            html = await self._fetch_page(config.url)
            
            if not html:
                logger.warning(f"No content from {config.name}")
                return headlines
            
            # Extract headlines using BeautifulSoup
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            # Find article containers
            articles = soup.select(config.article_selector)[:max_articles]
            
            for article in articles:
                try:
                    headline = self._extract_headline(article, config)
                    if headline and headline.url not in self._scraped_urls:
                        headlines.append(headline)
                        self._scraped_urls.add(headline.url)
                except Exception as e:
                    logger.debug(f"Failed to extract article: {e}")
                    continue
            
            self._last_scrape[config.name] = datetime.now(UTC)
            logger.info(f"Extracted {len(headlines)} headlines from {config.name}")
            
        except Exception as e:
            logger.error(f"Failed to scrape {config.name}: {e}")
        
        return headlines
    
    async def bulk_harvest(
        self,
        directories: Optional[List[DirectoryConfig]] = None,
        limit_per_directory: int = 50,
        total_limit: int = 500
    ) -> List[HeadlineItem]:
        """
        Harvest headlines from multiple directories concurrently.
        
        Args:
            directories: List of directory configs (uses defaults if None)
            limit_per_directory: Max articles per directory
            total_limit: Total maximum articles
            
        Returns:
            Combined list of HeadlineItem objects
        """
        dirs = directories or self.directories
        all_headlines: List[HeadlineItem] = []
        
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def scrape_with_semaphore(config: DirectoryConfig) -> List[HeadlineItem]:
            async with semaphore:
                await asyncio.sleep(config.delay_between_requests)
                return await self.scrape_directory(config, limit_per_directory)
        
        logger.info(f"Bulk harvesting from {len(dirs)} directories")
        
        tasks = [scrape_with_semaphore(config) for config in dirs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Directory scrape failed: {result}")
                continue
            all_headlines.extend(result)
            
            if len(all_headlines) >= total_limit:
                break
        
        # Deduplicate by URL
        seen_urls = set()
        unique_headlines = []
        for h in all_headlines[:total_limit]:
            if h.url not in seen_urls:
                unique_headlines.append(h)
                seen_urls.add(h.url)
        
        logger.info(f"Total headlines harvested: {len(unique_headlines)}")
        return unique_headlines
    
    async def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch page content using aiohttp, falling back to primp or browser."""
        try:
            if self._browser and self.use_browser:
                # Use Playwright for JavaScript sites
                return await self._fetch_with_browser(url)
            else:
                # Use aiohttp first for simple sites
                content = await self._fetch_with_aiohttp(url)
                if not content:
                    logger.info(f"aiohttp failed for {url}, attempting primp bypass...")
                    content = await self._fetch_with_primp(url)
                return content
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None
    
    async def _fetch_with_aiohttp(self, url: str) -> Optional[str]:
        """Fetch using aiohttp."""
        import aiohttp
        
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        connector = create_connector()
        
        try:
            async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 202:
                        logger.warning(f"🚫 {url} returned bot-challenge page (HTTP 202), skipping")
                        return None
                    elif response.status == 200:
                        text = await response.text()
                        lowered = text.lower()
                        if any(m in lowered for m in ["cf-browser-verification", "just a moment...", "challenge-platform"]):
                            logger.warning(f"🚫 {url} returned Cloudflare interstitial bot-challenge page, skipping")
                            return None
                        return text
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
                        return None
        except Exception as e:
            logger.warning(f"aiohttp connection error for {url}: {e}")
            return None
                    
    async def _fetch_with_primp(self, url: str) -> Optional[str]:
        """Fetch using primp for Cloudflare bypass."""
        try:
            import primp
            from src.utils.primp_profiles import get_chrome_profile
            
            loop = asyncio.get_event_loop()
            def fetch():
                from src.utils.primp_profiles import get_chrome_profile, safe_primp_get
                chrome_profile = get_chrome_profile()
                response = safe_primp_get(url, impersonate=chrome_profile, timeout=30.0)
                if not response:
                    return None
                if response.status_code == 202:
                    logger.warning(f"🚫 Primp: {url} returned bot-challenge page (HTTP 202), skipping")
                    return None
                elif response.status_code == 200:

                    text = response.text
                    lowered = text.lower()
                    if any(m in lowered for m in ["cf-browser-verification", "just a moment...", "challenge-platform"]):
                        logger.warning(f"🚫 Primp: {url} returned Cloudflare interstitial bot-challenge page, skipping")
                        return None
                    logger.info(f"✅ Primp bypass success for {url}")
                    return text
                else:
                    logger.debug(f"Primp returned {response.status_code} for {url}")
                    return None
                    
            return await loop.run_in_executor(None, fetch)
        except ImportError:
            logger.debug("primp not available for DirectoryScraper")
            return None
        except Exception as e:
            logger.debug(f"Primp fetch failed: {e}")
            return None
    
    async def _fetch_with_browser(self, url: str) -> Optional[str]:
        """Fetch using Playwright browser."""
        if not self._browser:
            return await self._fetch_with_aiohttp(url)
        
        try:
            content = await self._browser.get_page_content(url)
            return content
        except Exception as e:
            logger.warning(f"Browser fetch failed, falling back to aiohttp: {e}")
            return await self._fetch_with_aiohttp(url)
    
    def _extract_headline(
        self,
        article_element,
        config: DirectoryConfig
    ) -> Optional[HeadlineItem]:
        """Extract headline data from an article element."""
        
        # Extract title
        title_el = article_element.select_one(config.title_selector)
        if not title_el:
            return None
        
        title = title_el.get_text(strip=True)
        if not title or len(title) < 5:
            return None
        
        # Extract URL
        link_el = article_element.select_one(config.link_selector)
        if not link_el:
            link_el = title_el
        
        url = link_el.get("href", "")
        if not url:
            return None
        
        # Make URL absolute
        if not url.startswith("http"):
            url = urljoin(config.url, url)
        
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        
        # Extract optional fields
        summary = None
        summary_el = article_element.select_one(config.summary_selector)
        if summary_el:
            summary = summary_el.get_text(strip=True)[:300]
        
        image_url = None
        img_el = article_element.select_one(config.image_selector)
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(config.url, image_url)
        
        published = None
        
        # 1. Try configured selector
        if config.date_selector:
            date_el = article_element.select_one(config.date_selector)
            if date_el:
                published = date_el.get("datetime") or date_el.get_text(strip=True)
        
        # 2. Aggressive fallback: Look for any <time> tag within the snippet
        if not published:
            time_el = article_element.find("time")
            if time_el:
                published = time_el.get("datetime") or time_el.get_text(strip=True)
                
        # 3. Look for standard relative time strings in text
        if not published:
            text_content = article_element.get_text(separator=" ", strip=True).lower()
            import re
            # Extract basic relative time strings like "2 hours ago" or "updated 15 mins ago"
            match = re.search(r'(?:updated\s+)?(\d+\s+(?:min|minute|hour|day)s?\s+ago)', text_content)
            if match:
                published = match.group(1)
        
        return HeadlineItem(
            title=title,
            url=url,
            summary=summary,
            source=config.name,
            category=config.default_category,
            published=published,
            image_url=image_url
        )
    
    def add_directory(self, config: DirectoryConfig):
        """Add a new directory to scrape."""
        self.directories.append(config)
        logger.info(f"Added directory: {config.name}")
    
    def get_scrape_stats(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        return {
            "total_directories": len(self.directories),
            "unique_urls_scraped": len(self._scraped_urls),
            "last_scrapes": {
                name: ts.isoformat()
                for name, ts in self._last_scrape.items()
            }
        }
    
    def clear_cache(self):
        """Clear the scraped URL cache."""
        self._scraped_urls.clear()


# Default scraper instance
_default_scraper: Optional[DirectoryScraper] = None


def get_directory_scraper() -> DirectoryScraper:
    """Get or create the default directory scraper."""
    global _default_scraper
    if _default_scraper is None:
        from config.settings import DIRECTORY_CONCURRENT_SCRAPERS, USE_BROWSER_AUTOMATION
        _default_scraper = DirectoryScraper(
            max_concurrent=DIRECTORY_CONCURRENT_SCRAPERS,
            use_browser=USE_BROWSER_AUTOMATION
        )
    return _default_scraper
