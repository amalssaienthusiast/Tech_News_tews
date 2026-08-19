"""
Real-Time News Feeder with streaming and efficient timestamp sorting.

This module provides real-time news streaming capabilities:
- Incremental fetching (only new articles)
- Automatic deduplication by URL
- Time-based sorting using heap
- Background refresh with configurable interval
- Event-based notifications for new articles

DSA Used:
- Min-heap for timestamp ordering: O(log n) insert
- Bloom filter for deduplication: O(1) lookup
- LRU cache for HTTP responses: O(1) access
"""

import asyncio
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

# Ensure project imports work
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.types import Article, SourceTier, TechScore
from src.utils.http import create_connector
from src.data_structures import (
    ArticlePriorityQueue,
    BloomFilter,
    HTTPResponseCache,
    TechKeywordMatcher,
)
from src.engine.deep_scraper import ContentExtractor, DeepScraper

logger = logging.getLogger(__name__)


# =============================================================================
# ROBUST DATE PARSER
# =============================================================================

class RobustDateParser:
    """
    Robust date parser supporting 20+ formats.
    
    Handles:
    - ISO 8601: 2025-01-12T09:30:00Z
    - RFC 2822: Sun, 12 Jan 2025 09:30:00 +0000
    - Relative: "2 hours ago", "yesterday"
    - Human: "January 12, 2025", "12/01/2025"
    - URL patterns: /2025/01/12/
    """
    
    # Standard datetime formats to try
    DATETIME_FORMATS = [
        # ISO 8601 variants
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        # Date only
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        # Human readable
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y at %I:%M %p",
        "%b %d, %Y at %I:%M %p",
        # RFC 2822
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        # Other common formats
        "%Y%m%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
    ]
    
    # Relative time patterns
    RELATIVE_PATTERNS = [
        (r"(?:updated\s+|posted\s+)?(\d+)\s*(?:second|sec)s?\s*ago", "seconds"),
        (r"(?:updated\s+|posted\s+)?(\d+)\s*(?:minute|min)s?\s*ago", "minutes"),
        (r"(?:updated\s+|posted\s+)?(\d+)\s*(?:hour|hr)s?\s*ago", "hours"),
        (r"(?:updated\s+|posted\s+)?(\d+)\s*days?\s*ago", "days"),
        (r"(?:updated\s+|posted\s+)?(\d+)\s*weeks?\s*ago", "weeks"),
        (r"(?:updated\s+|posted\s+)?(\d+)\s*months?\s*ago", "months"),
        (r"(?:updated\s+|posted\s+)?yesterday", "yesterday"),
        (r"(?:updated\s+|posted\s+)?today", "today"),
        (r"(?:updated\s+|posted\s+)?just\s*now", "just_now"),
        (r"(?:updated\s+|posted\s+)?moments?\s*ago", "just_now"),
    ]
    
    # URL date pattern
    URL_DATE_PATTERN = re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})/")
    
    @classmethod
    def parse(cls, date_str: Optional[str], url: Optional[str] = None) -> Optional[datetime]:
        """
        Parse a date string using multiple strategies.
        
        Args:
            date_str: Date string to parse
            url: Optional URL for extracting date from path
        
        Returns:
            Parsed datetime or None if failed
        """
        if not date_str:
            # Try URL-based extraction
            if url:
                return cls._parse_from_url(url)
            return None
        
        # Clean the string
        date_str = date_str.strip()
        
        # Try relative time first
        result = cls._parse_relative(date_str)
        if result:
            return result
        
        # Try standard formats
        result = cls._parse_formats(date_str)
        if result:
            return result
        
        # Try dateutil as fallback
        result = cls._parse_dateutil(date_str)
        if result:
            return result
        
        # Try URL as last resort
        if url:
            return cls._parse_from_url(url)
        
        return None
    
    @classmethod
    def _parse_relative(cls, date_str: str) -> Optional[datetime]:
        """Parse relative time expressions."""
        date_lower = date_str.lower()
        now = datetime.now(UTC)
        
        for pattern, unit in cls.RELATIVE_PATTERNS:
            match = re.search(pattern, date_lower, re.IGNORECASE)
            if match:
                if unit == "yesterday":
                    return now - timedelta(days=1)
                elif unit == "today":
                    return now
                elif unit == "just_now":
                    return now
                else:
                    value = int(match.group(1))
                    if unit == "seconds":
                        return now - timedelta(seconds=value)
                    elif unit == "minutes":
                        return now - timedelta(minutes=value)
                    elif unit == "hours":
                        return now - timedelta(hours=value)
                    elif unit == "days":
                        return now - timedelta(days=value)
                    elif unit == "weeks":
                        return now - timedelta(weeks=value)
                    elif unit == "months":
                        return now - timedelta(days=value * 30)
        
        return None
    
    @classmethod
    def _parse_formats(cls, date_str: str) -> Optional[datetime]:
        """Try standard datetime formats."""
        for fmt in cls.DATETIME_FORMATS:
            try:
                dt = datetime.strptime(date_str, fmt)
                # Add UTC timezone if missing
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except ValueError:
                continue
        return None
    
    TZINFOS = {
        "EDT": -14400, "EST": -18000,
        "CDT": -18000, "CST": -21600,
        "MDT": -21600, "MST": -25200,
        "PDT": -25200, "PST": -28800,
        "UTC": 0, "GMT": 0, "BST": 3600, "CET": 3600, "CEST": 7200,
    }

    @classmethod
    def _parse_dateutil(cls, date_str: str) -> Optional[datetime]:
        """Use dateutil for flexible parsing."""
        try:
            from dateutil import parser as dateutil_parser
            dt = dateutil_parser.parse(date_str, fuzzy=True, tzinfos=cls.TZINFOS)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except Exception:
            return None
    
    @classmethod
    def _parse_from_url(cls, url: str) -> Optional[datetime]:
        """Extract date from URL path."""
        match = cls.URL_DATE_PATTERN.search(url)
        if match:
            try:
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                return None
        return None


# =============================================================================
# ENHANCED CONTENT EXTRACTOR
# =============================================================================

class EnhancedContentExtractor(ContentExtractor):
    """
    Enhanced content extractor with improved date extraction.
    """
    
    @classmethod
    def _extract_published_date(cls, soup: BeautifulSoup, url: str = "") -> Optional[str]:
        """
        Extract publication date with priority order.
        
        Priority:
        1. article:published_time
        2. datePublished (schema.org)
        3. time[datetime]
        4. ld+json structured data
        5. Common date classes
        6. URL date patterns
        """
        # 1. OpenGraph published_time
        og_time = soup.find('meta', property='article:published_time')
        if og_time and og_time.get('content'):
            val = og_time.get('content')
            return str(val) if not isinstance(val, list) else str(val[0])
        
        # Also check og:article:published_time
        og_time2 = soup.find('meta', property='og:article:published_time')
        if og_time2 and og_time2.get('content'):
            val2 = og_time2.get('content')
            return str(val2) if not isinstance(val2, list) else str(val2[0])
        
        # 2. Schema.org datePublished
        date_pub = soup.find(itemprop='datePublished')
        if date_pub:
            res = date_pub.get('content') or date_pub.get('datetime') or date_pub.get_text(strip=True)
            if res:
                return str(res) if not isinstance(res, list) else str(res[0])
        
        # 3. time element with datetime
        time_elem = soup.find('time', datetime=True)
        if time_elem:
            t_val = time_elem.get('datetime')
            if t_val:
                return str(t_val) if not isinstance(t_val, list) else str(t_val[0])

        
        # 4. ld+json structured data
        json_ld = cls._extract_json_ld_date(soup)
        if json_ld:
            return json_ld
        
        # 5. Common date classes
        date_selectors = [
            '.date', '.post-date', '.article-date', '.publish-date',
            '.entry-date', '.meta-date', '.timestamp', '.byline-date',
            '[class*="date"]', '[class*="time"]', '[class*="publish"]',
        ]
        
        for selector in date_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                # Skip if too long (probably not a date)
                if text and len(text) < 50:
                    return text
        
        # 6. URL pattern extraction will be handled by RobustDateParser
        return None
    
    @classmethod
    def _extract_json_ld_date(cls, soup: BeautifulSoup) -> Optional[str]:
        """Extract date from JSON-LD structured data."""
        import json
        
        scripts = soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string or '{}')
                
                # Handle array of objects
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            date = item.get('datePublished') or item.get('dateCreated')
                            if date:
                                return str(date)
                elif isinstance(data, dict):
                    date = data.get('datePublished') or data.get('dateCreated')
                    if date:
                        return str(date)
                    
                    # Check nested @graph
                    graph = data.get('@graph', [])
                    for item in graph:
                        if isinstance(item, dict):
                            date = item.get('datePublished') or item.get('dateCreated')
                            if date:
                                return str(date)

            except (json.JSONDecodeError, TypeError):
                continue
        
        return None


# =============================================================================
# REALTIME NEWS FEEDER
# =============================================================================

class RealtimeNewsFeeder:
    """
    Real-time news streaming with efficient timestamp sorting.
    
    Features:
    - Incremental fetching (only new articles since last refresh)
    - Automatic URL deduplication with Bloom filter
    - Time-based sorting using heap
    - Background auto-refresh
    - Async streaming interface
    
    DSA Summary:
    - ArticlePriorityQueue (heap): O(log n) insert, O(k log n) get top k
    - BloomFilter: O(1) deduplication check
    - HTTPResponseCache (LRU): O(1) response caching
    
    Example:
        feeder = RealtimeNewsFeeder(refresh_interval=300)
        await feeder.start()
        
        # Get latest articles
        latest = feeder.get_latest(20)
        
        # Stream new articles
        async for article in feeder.stream():
            print(f"New: {article.title} ({article.published_at})")
    """
    
    @property
    def DEFAULT_SOURCES(self) -> list[str]:
        """Dynamically load unified sources from data/custom_sources.json."""
        try:
            from src.sources.custom_source_loader import CustomSourceManager
            return CustomSourceManager.load_sources()
        except Exception as e:
            logger.debug(f"Failed to load custom_sources.json: {e}")
            return []

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    def __init__(
        self,
        refresh_interval: int = 300,
        max_articles: int = 500,
        max_age_hours: int = 24,
        sources: Optional[List[str]] = None
    ):
        """
        Initialize the real-time feeder.
        
        Args:
            refresh_interval: Seconds between auto-refreshes
            max_articles: Maximum articles to keep in memory
            max_age_hours: Maximum article age to keep
            sources: List of source URLs to monitor
        """
        self._refresh_interval = refresh_interval
        self._max_articles = max_articles
        self._max_age_hours = max_age_hours

        # Sources dynamically loaded from data/custom_sources.json
        self._sources = sources if sources is not None else self.DEFAULT_SOURCES



        
        # Data structures
        self._article_queue = ArticlePriorityQueue(
            max_size=max_articles,
            max_age_hours=max_age_hours,
            deduplicate=True
        )
        self._url_bloom = BloomFilter(expected_items=10000, false_positive_rate=0.01)
        self._response_cache = HTTPResponseCache(max_responses=100, default_ttl=300)
        self._keyword_matcher = TechKeywordMatcher()
        
        # Shared HTTP session (created lazily, closed on stop)
        self._session: Optional[aiohttp.ClientSession] = None
        
        # State
        self._last_refresh: Optional[datetime] = None
        self._running = False
        self._refresh_task: Optional[asyncio.Task] = None
        self._new_article_callbacks: List[Callable[[Article], None]] = []
        
        # Statistics
        self._stats = {
            "total_fetches": 0,
            "articles_added": 0,
            "duplicates_skipped": 0,
            "fetch_errors": 0,
            "refreshes": 0,
        }
    
    def __del__(self):
        """Destructor to ensure session is closed on garbage collection."""
        if self._session and not self._session.closed:
            # Schedule session close if there's a running event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._session.close())
            except RuntimeError:
                # No running event loop, try to close synchronously
                # This won't fully close but prevents some warnings
                pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensures cleanup."""
        await self.stop()
        return False
    
    async def start(self, fresh_start: bool = True) -> None:
        """
        Start the background refresh task.
        
        Args:
            fresh_start: If True, clears old articles before initial fetch
                        to ensure only fresh content is displayed at launch.
        """
        if self._running:
            return
        
        self._running = True
        
        # Clear old articles for fresh start (launch behavior)
        if fresh_start:
            self._article_queue.clear()
            self._url_bloom = BloomFilter(expected_items=10000, false_positive_rate=0.01)
            logger.info("Cleared old articles for fresh start")
        
        # Initial fetch
        await self.refresh()
        
        # Start background refresh
        self._refresh_task = asyncio.create_task(self._background_refresh())
        
        logger.info(f"RealtimeNewsFeeder started with {len(self._sources)} sources")
    
    async def stop(self) -> None:
        """Stop the background refresh task and close session."""
        self._running = False
        
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        
        # Close the shared session to prevent resource leak
        await self.close_session()
        
        logger.info("RealtimeNewsFeeder stopped (session closed)")
    
    async def close_session(self) -> None:
        """Close the aiohttp session to prevent resource leak."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Allow time for connector to drain connections
            await asyncio.sleep(0.25)
            self._session = None
    
    async def _background_refresh(self) -> None:
        """Background task for periodic refresh."""
        logger.info(f"Background refresh task started (interval: {self._refresh_interval}s)")
        while self._running:
            try:
                logger.debug(f"Next auto-refresh in {self._refresh_interval} seconds...")
                await asyncio.sleep(self._refresh_interval)
                logger.info("Auto-refresh triggered by background task")
                await self.refresh()
            except asyncio.CancelledError:
                logger.info("Background refresh task cancelled")
                break
            except Exception as e:
                logger.error(f"Background refresh error: {e}")

    
    async def refresh(self) -> int:
        """
        Refresh articles from all sources.
        
        Returns:
            Number of new articles added
        """
        logger.info("Refreshing real-time news feed...")
        start_time = time.time()
        new_articles = 0
        
        self._stats["refreshes"] += 1
        
        # Use shared session (create lazily if needed)
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": self.USER_AGENT},
                connector=create_connector()
            )
        
        session = self._session
        
        # Fetch sources concurrently with a semaphore to prevent overloading
        sem = asyncio.Semaphore(15)  # Limit to 15 concurrent fetches
        
        async def fetch_with_sem(source):
            async with sem:
                return await self._fetch_source(session, source)
                
        tasks = [
            fetch_with_sem(source)
            for source in self._sources
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for articles in results:
            if isinstance(articles, list):
                for article in articles:
                    if self._add_article(article):
                        new_articles += 1
                        # Notify callbacks
                        for callback in self._new_article_callbacks:
                            try:
                                callback(article)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
        
        self._last_refresh = datetime.now(UTC)
        duration = (time.time() - start_time) * 1000
        
        # Clean up expired articles
        self._article_queue.remove_expired()
        
        logger.info(
            f"Refresh complete: {new_articles} new articles in {duration:.0f}ms"
        )
        
        return new_articles
    
    async def _fetch_with_bypass(self, url: str) -> Optional[str]:
        """
        Enhanced bypass with multiple strategies using thread-safe TLS client calls.
        """
        if not self._running:
            return None

        import random
        import threading

        if not hasattr(self, '_primp_lock'):
            self._primp_lock = threading.Lock()
        
        # Strategy 1: Standard requests with advanced headers
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]

        # Bug fix: use certifi CA bundle so requests works on macOS (system SSL store not used by requests)
        try:
            import certifi as _certifi
            _ssl_verify: Any = _certifi.where()
        except ImportError:
            _ssl_verify = True  # fall back to default (may fail on macOS)

        for i, ua in enumerate(user_agents):
            try:
                import requests

                headers = {
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate",
                    "Referer": "https://www.google.com/search?q=technology+news",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "max-age=0",
                }

                # Use thread pool for sync requests in async context
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.get(url, headers=headers, timeout=15, verify=_ssl_verify)
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Bypass success (requests #{i+1}): {url}")
                    return response.text
                else:
                    logger.debug(f"Bypass attempt {i+1} returned {response.status_code}")
                    
            except Exception as e:
                logger.debug(f"Bypass attempt {i+1} failed: {e}")
        
        # Strategy 2: Primp with Chrome (thread-safe TLS impersonation)
        try:
            from src.utils.primp_profiles import get_chrome_profile, safe_primp_get
            chrome_profile = get_chrome_profile()
            loop = asyncio.get_running_loop()

            response = await loop.run_in_executor(
                None,
                lambda: safe_primp_get(url, impersonate=chrome_profile, timeout=15.0)
            )

            if response and response.status_code == 200:
                logger.info(f"✅ Bypass success (primp {chrome_profile}): {url}")
                return response.text
            elif response:
                logger.debug(f"Primp chrome returned {response.status_code}")

        except Exception as e:
            logger.debug(f"Primp chrome failed: {e}")

        # Strategy 3: Primp with Firefox (thread-safe TLS impersonation)
        try:
            from src.utils.primp_profiles import get_firefox_profile, safe_primp_get
            firefox_profile = get_firefox_profile()
            loop = asyncio.get_running_loop()

            response = await loop.run_in_executor(
                None,
                lambda: safe_primp_get(url, impersonate=firefox_profile, timeout=15.0)
            )
            
            if response and response.status_code == 200:
                logger.info(f"✅ Bypass success (primp {firefox_profile}): {url}")
                return response.text
            elif response:
                logger.debug(f"Primp firefox returned {response.status_code}")
                
        except Exception as e:
            logger.debug(f"Primp firefox failed: {e}")

        
        # Strategy 4: curl_cffi (advanced TLS)
        try:
            import curl_cffi.requests
            from src.utils.primp_profiles import get_chrome_profile_curl

            curl_profile = get_chrome_profile_curl()
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: curl_cffi.requests.get(url, impersonate=curl_profile, timeout=15)
            )
            
            if response and response.status_code == 200:
                logger.info(f"✅ Bypass success (curl_cffi {curl_profile}): {url}")
                return response.text
            elif response:
                logger.debug(f"curl_cffi returned {response.status_code}")
                
        except ImportError:
            logger.debug("curl_cffi not available")
        except Exception as e:
            logger.debug(f"curl_cffi failed: {e}")

        # Strategy 5: Search Engine Crawler Emulation (Googlebot / Bingbot)
        try:
            from src.bypass import get_googlebot_headers
            headers = get_googlebot_headers()
            loop = asyncio.get_running_loop()
            import requests

            response = await loop.run_in_executor(
                None,
                lambda: requests.get(url, headers=headers, timeout=15, verify=_ssl_verify)
            )
            if response and response.status_code == 200:
                logger.info(f"✅ Bypass success (Googlebot Emulation): {url}")
                return response.text
        except Exception as e:
            logger.debug(f"Googlebot emulation bypass failed: {e}")

        # Strategy 6: AntiBotBypass Smart Fallback Subsystem
        try:
            from src.bypass import AntiBotBypass
            anti_bot = AntiBotBypass()
            content, strategy = await anti_bot.smart_fetch_with_fallback(url)
            if content and len(content) > 100:
                logger.info(f"✅ Bypass success (AntiBotBypass - {strategy}): {url}")
                return content
        except Exception as e:
            logger.debug(f"AntiBotBypass failed: {e}")

        # Strategy 7: Content Platform Bypass (Medium, Substack, Hashnode)
        try:
            from src.bypass import bypass_content_platform
            platform_result = await bypass_content_platform(url)
            if platform_result and platform_result.content:
                logger.info(f"✅ Bypass success (ContentPlatformBypass - {platform_result.platform}): {url}")
                return platform_result.content
        except Exception as e:
            logger.debug(f"ContentPlatformBypass failed: {e}")

        logger.warning(f"❌ All bypass strategies failed for: {url}")
        return None

        return None
    
    async def _fetch_source(
        self,
        session: aiohttp.ClientSession,
        source_url: str
    ) -> List[Article]:
        """Fetch articles from an RSS/Atom feed source with resilient fallback."""
        import feedparser
        import hashlib
        from urllib.parse import urlparse

        articles = []
        content = None

        try:
            self._stats["total_fetches"] += 1

            # ATTEMPT 1: Try standard aiohttp first (fastest)
            try:
                async with session.get(
                    source_url,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        content = await response.text()
                    elif response.status == 403:
                        # Blocked — will try bypass below
                        logger.debug(f"🚫 Standard fetch blocked (403): {source_url}")
                    else:
                        logger.warning(f"HTTP {response.status}: {source_url}")
                        self._stats["fetch_errors"] += 1
                        return articles
            except Exception as e:
                logger.debug(f"Standard fetch failed: {e}")

            # ATTEMPT 2: Use bypass if standard failed or was blocked
            if content is None:
                logger.info(f"🔓 Attempting bypass for: {source_url}")
                content = await self._fetch_with_bypass(source_url)

                if content:
                    self._stats["bypass_success"] = self._stats.get("bypass_success", 0) + 1
                else:
                    self._stats["fetch_errors"] += 1
                    return articles

            # --- Parse content (runs for BOTH standard and bypass paths) ---
            # Bug fix: previously this block was nested inside "if content is None"
            # (the bypass branch), so standard-path fetches returned 0 articles.
            if content:
                feed = feedparser.parse(content)

                if feed.bozo and not feed.entries:
                    # RSS parsing failed — try HTML fallback extraction
                    logger.debug(f"RSS parse failed for {source_url}, trying HTML fallback")
                    soup = BeautifulSoup(content, 'html.parser')
                    articles = self._extract_articles_from_page(soup, source_url)
                else:
                    # Successfully parsed RSS/Atom feed
                    source_name = feed.feed.get('title', urlparse(source_url).netloc)

                    for entry in feed.entries[:30]:  # Limit per feed
                        try:
                            # Extract article URL
                            link = entry.get('link', '')
                            if not link:
                                continue

                            # Skip if already seen
                            if link in self._url_bloom:
                                continue

                            # Extract title
                            title = entry.get('title', '')
                            if not title or len(title) < 10:
                                continue

                            # Extract description/summary
                            summary = entry.get('summary', entry.get('description', ''))
                            # Strip HTML from summary
                            if summary:
                                summary_soup = BeautifulSoup(summary, 'html.parser')
                                summary = summary_soup.get_text(strip=True)[:500]

                            # Extract published date
                            published_str = entry.get('published', entry.get('updated', ''))
                            published_at = RobustDateParser.parse(published_str, link)

                            # Generate article ID
                            article_id = hashlib.md5(link.encode()).hexdigest()

                            article = Article(
                                id=article_id,
                                url=link,
                                title=title[:200],
                                content=summary or "",
                                summary=summary or "",
                                source=source_name,
                                source_tier=SourceTier.TIER_2,
                                published_at=published_at,
                                scraped_at=datetime.now(UTC),
                            )

                            articles.append(article)

                        except Exception as e:
                            logger.debug(f"Error parsing RSS entry: {e}")
                            continue

                    logger.info(f"RSS feed {source_url}: {len(articles)} articles")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout: {source_url}")
            self._stats["fetch_errors"] += 1
        except Exception as e:
            logger.warning(f"Error fetching {source_url}: {e}")
            self._stats["fetch_errors"] += 1

        return articles
    
    def _extract_articles_from_page(
        self,
        soup: BeautifulSoup,
        source_url: str
    ) -> List[Article]:
        """Extract articles from a parsed page."""
        from urllib.parse import urljoin, urlparse
        import hashlib
        
        articles = []
        base_domain = urlparse(source_url).netloc
        
        # Find article links
        for link in soup.find_all('a', href=True):
            href = link['href']
            url = urljoin(source_url, href)
            
            # Skip if already seen
            if url in self._url_bloom:
                continue
            
            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme.startswith('http'):
                continue
            if parsed.netloc != base_domain:
                continue
            
            # Check if likely article URL
            if not self._is_article_url(url):
                continue
            
            # Extract metadata from link context
            anchor_text = link.get_text(strip=True)
            
            # Skip if title is too short
            if len(anchor_text) < 20:
                continue
            
            # Try to find date near the link
            parent = link.parent
            date_str = None
            
            if parent:
                time_elem = parent.find('time')
                if time_elem:
                    date_str = time_elem.get('datetime') or time_elem.get_text(strip=True)
                else:
                    # Look for date patterns in parent text
                    parent_text = parent.get_text()
                    date_str = self._extract_date_from_text(parent_text)
            
            # Parse date
            published_at = RobustDateParser.parse(date_str, url)
            
            # Create article
            article_id = hashlib.md5(url.encode()).hexdigest()
            
            article = Article(
                id=article_id,
                url=url,
                title=anchor_text[:200],
                content="",  # Content would be fetched on demand
                summary="",
                source=base_domain,
                source_tier=SourceTier.TIER_2,
                published_at=published_at,
                scraped_at=datetime.now(UTC),
            )
            
            articles.append(article)
            
            # Limit articles per source
            if len(articles) >= 20:
                break
        
        return articles
    
    def _is_article_url(self, url: str) -> bool:
        """Check if URL is likely an article."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Skip patterns
        skip_patterns = [
            '/tag/', '/category/', '/author/', '/page/',
            '/search', '/login', '/register', '/about',
            '/contact', '/privacy', '/terms',
            '.pdf', '.jpg', '.png', '.gif', '.mp4',
        ]
        
        for pattern in skip_patterns:
            if pattern in path:
                return False
        
        # Positive patterns
        article_patterns = [
            '/article/', '/news/', '/post/', '/story/',
            '/blog/', '/feature/', '/review/',
            r'/\d{4}/', # Year in URL
        ]
        
        for pattern in article_patterns:
            if re.search(pattern, path):
                return True
        
        # Check path length (articles usually have longer paths)
        if len(path) > 20:
            return True
        
        return False
    
    def _extract_date_from_text(self, text: str) -> Optional[str]:
        """Extract date from surrounding text."""
        # Common date patterns in text
        patterns = [
            r'\b(\w+ \d{1,2}, \d{4})\b',  # January 12, 2025
            r'\b(\d{1,2}/\d{1,2}/\d{4})\b',  # 01/12/2025
            r'\b(\d{4}-\d{2}-\d{2})\b',  # 2025-01-12
            r'\b(\d+ (?:hour|minute|day)s? ago)\b',  # relative
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _add_article(self, article: Article) -> bool:
        """Add article to queue with deduplication."""
        if article.url in self._url_bloom:
            self._stats["duplicates_skipped"] += 1
            return False
        
        # Add to bloom filter
        self._url_bloom.add(article.url)
        
        # Add to priority queue
        if self._article_queue.push(article):
            self._stats["articles_added"] += 1
            return True
        
        return False
    
    def get_latest(self, count: int = 20) -> List[Article]:
        """
        Get the most recent articles.
        
        Args:
            count: Number of articles to return
        
        Returns:
            List of articles sorted by timestamp (newest first)
        """
        return self._article_queue.get_latest(count)
    
    def get_last_n_hours(self, hours: int = 4) -> List[Article]:
        """Get articles from the last N hours."""
        return self._article_queue.get_last_n_hours(hours)
    
    def get_since(self, since: datetime) -> List[Article]:
        """Get articles published since a specific time."""
        return self._article_queue.get_in_time_range(since, datetime.now(UTC))
    
    async def stream(self) -> AsyncIterator[Article]:
        """
        Stream new articles as they arrive.
        
        Yields articles as they are discovered during refresh.
        """
        queue: asyncio.Queue[Article] = asyncio.Queue()
        
        def on_new_article(article: Article):
            try:
                queue.put_nowait(article)
            except asyncio.QueueFull:
                pass
        
        self._new_article_callbacks.append(on_new_article)
        
        try:
            while self._running:
                try:
                    article = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield article
                except asyncio.TimeoutError:
                    continue
        finally:
            self._new_article_callbacks.remove(on_new_article)
    
    def on_new_article(self, callback: Callable[[Article], None]) -> None:
        """Register a callback for new articles."""
        self._new_article_callbacks.append(callback)
    
    @property
    def article_count(self) -> int:
        """Get current article count."""
        return len(self._article_queue)
    
    @property
    def last_refresh(self) -> Optional[datetime]:
        """Get last refresh time."""
        return self._last_refresh
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get feeder statistics."""
        return {
            **self._stats,
            "queue_stats": self._article_queue.stats,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "sources": len(self._sources),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def get_realtime_news(
    count: int = 20,
    max_age_hours: int = 24,
    sources: Optional[List[str]] = None
) -> List[Article]:
    """
    Quick function to get real-time news sorted by timestamp.
    
    Args:
        count: Number of articles to return
        max_age_hours: Maximum article age
        sources: Optional custom sources
    
    Returns:
        List of articles sorted by timestamp (newest first)
    """
    feeder = RealtimeNewsFeeder(
        max_articles=count * 2,
        max_age_hours=max_age_hours,
        sources=sources
    )
    
    try:
        await feeder.refresh()
        return feeder.get_latest(count)
    finally:
        # Always close session to prevent resource leak
        await feeder.close_session()


async def stream_news(
    sources: Optional[List[str]] = None,
    refresh_interval: int = 300
) -> AsyncIterator[Article]:
    """
    Stream real-time news articles.
    
    Args:
        sources: Optional custom sources
        refresh_interval: Seconds between refreshes
    
    Yields:
        Articles as they are discovered
    """
    feeder = RealtimeNewsFeeder(
        refresh_interval=refresh_interval,
        sources=sources
    )
    
    await feeder.start()
    
    try:
        async for article in feeder.stream():
            yield article
    finally:
        await feeder.stop()
