"""
Google News Integration Module.

Provides multiple approaches to fetch news from Google:
1. Google News RSS feeds (free, 15-30 min delay)
2. Google Custom Search API (100 queries/day free)
3. SerpAPI for Google News (paid, real-time)
4. Google Trends for emerging topics

Usage:
    client = GoogleNewsClient()
    
    # Free RSS-based fetching
    articles = await client.fetch_rss_feeds()
    
    # API-based (requires GOOGLE_API_KEY + GOOGLE_CSE_ID)
    articles = await client.search("artificial intelligence")
    
    # Get trending topics
    topics = await client.get_trending_topics()
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse
from dataclasses import dataclass, field

import aiohttp
import feedparser

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class NewsArticle:
    """Normalized article structure from Google News."""
    id: str
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    description: str = ""
    image_url: str = ""
    category: str = ""
    topics: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "description": self.description,
            "image_url": self.image_url,
            "category": self.category,
            "topics": self.topics,
        }


# =============================================================================
# GOOGLE NEWS RSS FEEDS
# =============================================================================

class GoogleNewsRSS:
    """
    Google News RSS feed parser (free, no API key required).
    
    Provides access to:
    - Top headlines by country/language
    - Topic-specific feeds (Technology, Business, etc.)
    - Search-based feeds
    
    Note: RSS feeds have ~15-30 minute delay from real-time.
    """
    
    BASE_URL = "https://news.google.com/rss"
    
    # Topic feeds by Google News category
    TOPICS = {
        "technology": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB",
        "business": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB",
        "science": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB",
        "health": "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ",
        "entertainment": "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB",
    }
    
    # Country/language codes
    REGIONS = {
        "us": {"hl": "en", "gl": "US", "ceid": "US:en"},
        "uk": {"hl": "en", "gl": "GB", "ceid": "GB:en"},
        "in": {"hl": "en", "gl": "IN", "ceid": "IN:en"},
        "au": {"hl": "en", "gl": "AU", "ceid": "AU:en"},
        "ca": {"hl": "en", "gl": "CA", "ceid": "CA:en"},
        "de": {"hl": "en", "gl": "DE", "ceid": "DE:en"},
        "fr": {"hl": "en", "gl": "FR", "ceid": "FR:en"},
        "jp": {"hl": "en", "gl": "JP", "ceid": "JP:en"},
        "tw": {"hl": "en", "gl": "TW", "ceid": "TW:en"},
        "kr": {"hl": "en", "gl": "KR", "ceid": "KR:en"},
        "il": {"hl": "en", "gl": "IL", "ceid": "IL:en"},
        "cn": {"hl": "en", "gl": "CN", "ceid": "CN:en"},
        "sg": {"hl": "en", "gl": "SG", "ceid": "SG:en"},
        "se": {"hl": "en", "gl": "SE", "ceid": "SE:en"},
        "fi": {"hl": "en", "gl": "FI", "ceid": "FI:en"},
        "nl": {"hl": "en", "gl": "NL", "ceid": "NL:en"},
        "ch": {"hl": "en", "gl": "CH", "ceid": "CH:en"},
        "ee": {"hl": "en", "gl": "EE", "ceid": "EE:en"},
    }
    
    def __init__(self, region: str = "us"):
        """
        Initialize Google News RSS parser.
        
        Args:
            region: Country code
        """
        reg_key = region.lower()
        if reg_key in self.REGIONS:
            self._region = self.REGIONS[reg_key]
        else:
            code_upper = region.upper()
            self._region = {"hl": "en", "gl": code_upper, "ceid": f"{code_upper}:en"}
        self._user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    
    def _build_url(self, path: str = "", params: Dict[str, str] = None) -> str:
        """Build RSS feed URL with region params."""
        url = f"{self.BASE_URL}{path}"
        
        query_params = {
            "hl": self._region["hl"],
            "gl": self._region["gl"],
            "ceid": self._region["ceid"],
        }
        
        if params:
            query_params.update(params)
        
        query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
        return f"{url}?{query_string}"
    
    async def fetch_feed(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> List[NewsArticle]:
        """Fetch and parse an RSS feed."""
        articles = []
        
        try:
            headers = {"User-Agent": self._user_agent}
            async with session.get(url, headers=headers, timeout=30) as response:

                if response.status != 200:
                    logger.warning(f"Google News RSS returned {response.status}: {url}")
                    return articles
                
                content = await response.text()
                feed = feedparser.parse(content)
                
                for entry in feed.entries:
                    article = self._parse_entry(entry)
                    if article:
                        articles.append(article)
                
                logger.debug(f"Parsed {len(articles)} articles from Google News RSS")
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching Google News RSS: {url}")
        except Exception as e:
            logger.error(f"Error fetching Google News RSS: {e}")
        
        return articles
    
    def _parse_entry(self, entry: Any) -> Optional[NewsArticle]:
        """Parse a single RSS feed entry."""
        try:
            # Extract URL (Google News wraps URLs)
            url = self._extract_actual_url(entry.get("link", ""))
            if not url:
                return None
            
            # Generate ID
            article_id = hashlib.md5(url.encode()).hexdigest()
            
            # Parse publication date (support published_parsed, updated_parsed)
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published_at = datetime(*entry.updated_parsed[:6], tzinfo=UTC)

            # Extract source from title (Google News format: "Title - Source")
            title = entry.get("title", "")
            source = "Google News"
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0]
                source = parts[1] if len(parts) > 1 else source

            # Extract image_url from summary or media tags
            image_url = ""
            summary_html = entry.get("summary", "")
            if "<img" in summary_html.lower():
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(summary_html, "html.parser")
                    img = soup.find("img")
                    if img and img.get("src"):
                        src = img["src"]
                        if src.startswith("http") and not any(skip in src.lower() for skip in ["tracker", "pixel", "feedburner", "1x1"]):
                            image_url = src
                except Exception:
                    pass

            return NewsArticle(
                id=article_id,
                title=title,
                url=url,
                source=source,
                published_at=published_at,
                description=summary_html,
                image_url=image_url,
            )
            
        except Exception as e:
            logger.debug(f"Error parsing RSS entry: {e}")
            return None
    
    def _extract_actual_url(self, google_url: str) -> Optional[str]:
        """Extract actual article URL from Google News redirect URL."""
        if not google_url:
            return None
        
        # Google News uses redirect URLs like:
        # https://news.google.com/rss/articles/...
        # We need to follow the redirect or parse the URL
        
        # For RSS feeds, the URL is often already the final URL
        if "news.google.com" not in google_url:
            return google_url
        
        # Try to extract from URL parameters
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(google_url)
        
        if "url=" in google_url:
            params = parse_qs(parsed.query)
            if "url" in params:
                return params["url"][0]
        
        # Return the Google URL as-is (will need to follow redirect)
        return google_url
    
    async def get_top_headlines(
        self,
        session: aiohttp.ClientSession,
    ) -> List[NewsArticle]:
        """Fetch top headlines RSS feed."""
        url = self._build_url()
        return await self.fetch_feed(session, url)
    
    async def get_topic_feed(
        self,
        session: aiohttp.ClientSession,
        topic: str,
    ) -> List[NewsArticle]:
        """Fetch topic-specific RSS feed."""
        topic_id = self.TOPICS.get(topic.lower())
        if not topic_id:
            logger.warning(f"Unknown topic: {topic}")
            return []
        
        url = self._build_url(f"/topics/{topic_id}")
        articles = await self.fetch_feed(session, url)
        
        # Tag articles with topic
        for article in articles:
            article.category = topic
            article.topics.append(topic)
        
        return articles
    
    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
    ) -> List[NewsArticle]:
        """Search Google News RSS for a query."""
        encoded_query = quote_plus(query)
        url = self._build_url(f"/search", {"q": encoded_query})
        return await self.fetch_feed(session, url)


# =============================================================================
# GOOGLE CUSTOM SEARCH API
# =============================================================================

class GoogleCustomSearchClient:
    """
    Google Custom Search API client for news search.
    
    Requires:
    - GOOGLE_API_KEY
    - GOOGLE_CSE_ID (Custom Search Engine ID)
    
    Free tier: 100 queries/day
    
    Automatically falls back to RSS when quota is exhausted.
    """
    
    API_URL = "https://www.googleapis.com/customsearch/v1"
    
    # Class-level quota tracking (shared across instances)
    _quota_exhausted: bool = False
    _quota_exhausted_time: Optional[datetime] = None
    
    def __init__(self, api_key: str = "", cse_id: str = ""):
        """
        Initialize Google Custom Search client.
        
        Args:
            api_key: Google API key
            cse_id: Custom Search Engine ID
        """
        # Try to load from settings if not provided
        if not api_key or not cse_id:
            try:
                from config.settings import GOOGLE_API_KEY, GOOGLE_CSE_ID
                api_key = api_key or GOOGLE_API_KEY
                cse_id = cse_id or GOOGLE_CSE_ID
            except ImportError:
                logger.debug(
                    "config.settings not found; falling back to environment variables "
                    "for GOOGLE_API_KEY and GOOGLE_CSE_ID."
                )
        
        self._api_key = api_key
        self._cse_id = cse_id
        self._enabled = bool(api_key and cse_id)
        
        if not self._enabled:
            logger.warning(
                "Google Custom Search not configured. "
                "Set GOOGLE_API_KEY and GOOGLE_CSE_ID in .env"
            )
    
    @property
    def is_enabled(self) -> bool:
        """Check if API is configured."""
        return self._enabled
    
    def _should_reset_quota(self) -> bool:
        """Check if quota should be reset (next day boundary)."""
        if not GoogleCustomSearchClient._quota_exhausted_time:
            return False
        
        # Reset if it's been more than 24 hours
        time_since = datetime.now(UTC) - GoogleCustomSearchClient._quota_exhausted_time
        return time_since.total_seconds() > 86400  # 24 hours
    
    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
        num_results: int = 10,
        date_restrict: str = "d1",  # Last 24 hours
    ) -> List[NewsArticle]:
        """
        Search Google Custom Search for news articles.
        
        Args:
            session: aiohttp session
            query: Search query
            num_results: Number of results (max 10 per request)
            date_restrict: Date restriction (d1=1 day, w1=1 week, m1=1 month)
        
        Returns:
            List of NewsArticle objects
        """
        if not self._enabled:
            return []
        
        # Check quota status - skip if exhausted
        if GoogleCustomSearchClient._quota_exhausted:
            if self._should_reset_quota():
                GoogleCustomSearchClient._quota_exhausted = False
                GoogleCustomSearchClient._quota_exhausted_time = None
                logger.info("Google API quota reset - resuming API calls")
            else:
                # Silently skip - don't log repeated warnings
                return []
        
        articles = []
        
        try:
            params = {
                "key": self._api_key,
                "cx": self._cse_id,
                "q": query,
                "num": min(num_results, 10),
                "dateRestrict": date_restrict,
                "sort": "date",  # Sort by date
            }
            
            async with session.get(self.API_URL, params=params, timeout=30) as response:
                if response.status == 429:
                    # Quota exhausted - set flag and warn once
                    GoogleCustomSearchClient._quota_exhausted = True
                    GoogleCustomSearchClient._quota_exhausted_time = datetime.now(UTC)
                    logger.warning(
                        "Google Custom Search API quota exhausted (100/day limit). "
                        "Falling back to RSS-only mode until reset."
                    )
                    return articles
                
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"Google Search API error {response.status}: {error}")
                    return articles
                
                data = await response.json()
                
                for item in data.get("items", []):
                    article = self._parse_search_result(item)
                    if article:
                        articles.append(article)
                
                logger.info(f"Google Search: {len(articles)} results for '{query}'")
                
        except asyncio.TimeoutError:
            logger.warning("Google Search API timeout")
        except Exception as e:
            logger.error(f"Google Search API error: {e}")
        
        return articles
    
    def _parse_search_result(self, item: Dict) -> Optional[NewsArticle]:
        """Parse a single search result."""
        try:
            url = item.get("link", "")
            if not url:
                return None
            
            article_id = hashlib.md5(url.encode()).hexdigest()
            
            # Try to extract publication date from metadata
            published_at = None
            pagemap = item.get("pagemap", {})
            metatags = (pagemap.get("metatags") or [{}])[0]
            
            date_str = (
                metatags.get("article:published_time") or
                metatags.get("og:article:published_time") or
                metatags.get("datePublished")
            )
            if date_str:
                try:
                    from dateutil import parser
                    tzinfos = {
                        "EDT": -14400, "EST": -18000, "CDT": -18000, "CST": -21600,
                        "MDT": -21600, "MST": -25200, "PDT": -25200, "PST": -28800,
                        "UTC": 0, "GMT": 0, "BST": 3600, "CET": 3600, "CEST": 7200,
                    }
                    published_at = parser.parse(date_str, tzinfos=tzinfos)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=UTC)
                except (ValueError, OverflowError, ImportError) as exc:
                    logger.debug("Could not parse date '%s' from search result metadata: %s", date_str, exc)
            
            # Extract source from display link
            source = item.get("displayLink", urlparse(url).netloc)
            
            return NewsArticle(
                id=article_id,
                title=item.get("title", ""),
                url=url,
                source=source,
                published_at=published_at,
                description=item.get("snippet", ""),
            )
            
        except Exception as e:
            logger.debug(f"Error parsing search result: {e}")
            return None


# =============================================================================
# UNIFIED GOOGLE NEWS CLIENT
# =============================================================================

class GoogleNewsClient:

    EXPANDED_SEARCH_TOPICS = [
        # Core Google News categories (mapped to built-in topic IDs)
        "technology",
        "science",
        "health",
        # ── AI / Computing ───────────────────────────────────────────
        "artificial intelligence",
        "machine learning",
        "quantum computing",
        "cybersecurity",
        "semiconductor",
        "robotics",
        "blockchain technology",
        "cloud computing",
        "data science",
        # ── Science / Research ───────────────────────────────────────
        "space exploration",
        "astronomy",
        "physics research",
        "chemistry research",
        "materials science",
        "mathematics breakthrough",
        "climate science research",
        "renewable energy technology",
        # ── Biology / Biotech ────────────────────────────────────────
        "biotechnology",
        "genetics research",
        "neuroscience research",
        "gene therapy technology",
        "precision medicine technology",
        "drug discovery research",
        "cancer research breakthrough",
        "clinical trial results",
        # ── Industry / Applied Tech ──────────────────────────────────
        "electric vehicle technology",
        "autonomous vehicle",
        "drone technology",
        "5g 6g wireless technology",
        "iot internet of things",
        "startup funding technology",
        "fintech innovation",
        "green technology innovation",
        "nuclear fusion energy",
    ]

    """
    Unified Google News client combining RSS and API approaches.
    
    Automatically uses the best available method:
    1. Custom Search API (if configured) - most accurate, real-time
    2. RSS feeds (fallback) - free, 15-30 min delay
    
    Example:
        async with aiohttp.ClientSession() as session:
            client = GoogleNewsClient()
            
            # Get all tech news
            articles = await client.fetch_all(session, topic="technology")
            
            # Search for specific topic
            articles = await client.search(session, "ChatGPT updates")
    """
    
    def __init__(self, region: str = "us"):
        """
        Initialize Google News client.
        
        Args:
            region: Country code for news localization
        """
        self._rss = GoogleNewsRSS(region)
        self._api = GoogleCustomSearchClient()
    
    @property
    def api_enabled(self) -> bool:
        """Check if Custom Search API is available."""
        return self._api.is_enabled
    
    async def fetch_rss_feeds(
        self,
        session: aiohttp.ClientSession,
        topics: List[str] = None,
        include_headlines: bool = True,
    ) -> List[NewsArticle]:
        """
        Fetch from Google News RSS feeds.
        
        Args:
            session: aiohttp session
            topics: List of topics (technology, business, science, health)
            include_headlines: Include top headlines feed
        
        Returns:
            List of articles from RSS feeds
        """
        # Check cache (60s TTL) to prevent duplicate back-to-back passes in a single cycle
        now = datetime.now(UTC)
        if getattr(self, "_rss_cache", None) and getattr(self, "_rss_cache_time", None):
            elapsed = (now - self._rss_cache_time).total_seconds()
            if elapsed < 60 and not topics and not include_headlines:
                logger.info(f"Google News RSS (cached): {len(self._rss_cache)} articles ({elapsed:.0f}s old, skipping duplicate fetch)")
                return list(self._rss_cache)

        all_articles = []
        tasks = []
        
        # Top headlines
        if include_headlines:
            tasks.append(self._rss.get_top_headlines(session))
        
        # Topic feeds
        topics_to_fetch = topics if topics else self.EXPANDED_SEARCH_TOPICS
        
        sem = asyncio.Semaphore(5)  # Limit concurrent Google News requests
        
        async def fetch_topic_safely(t):
            async with sem:
                # If it is a built-in category, use get_topic_feed
                if t.lower() in self._rss.TOPICS:
                    return await self._rss.get_topic_feed(session, t)
                else:
                    # Otherwise, use search-based RSS feed
                    return await self._rss.search(session, t)
                    
        for topic in topics_to_fetch:
            tasks.append(fetch_topic_safely(topic))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"RSS fetch error: {result}")
        
        # Deduplicate by URL
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        self._rss_cache = unique_articles
        self._rss_cache_time = now
        logger.info(f"Google News RSS: {len(unique_articles)} unique articles")
        return unique_articles
    
    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
        use_api: bool = True,
        fallback_to_rss: bool = True,
    ) -> List[NewsArticle]:
        """
        Search Google News for articles matching query.
        
        Args:
            session: aiohttp session
            query: Search query
            use_api: Use Custom Search API if available
            fallback_to_rss: Fall back to RSS if API unavailable/fails
        
        Returns:
            List of matching articles
        """
        # Try API first
        if use_api and self._api.is_enabled:
            articles = await self._api.search(session, query)
            if articles:
                return articles
        
        # Fallback to RSS search
        if fallback_to_rss:
            return await self._rss.search(session, query)
        
        return []
    
    async def get_trending_topics(
        self,
        session: aiohttp.ClientSession,
    ) -> List[str]:
        """
        Get trending topics from Google Trends.
        
        Note: This is a simplified implementation.
        For full Google Trends integration, consider pytrends library.
        """
        # For now, return tech-related trending queries
        # In a full implementation, this would query Google Trends API
        trending = [
            "AI news today",
            "ChatGPT updates",
            "tech layoffs",
            "startup funding",
            "cybersecurity breach",
            "new iPhone",
            "electric vehicles",
            "cryptocurrency news",
        ]
        return trending
    
    async def fetch_all(
        self,
        session: aiohttp.ClientSession,
        topic: str = "technology",
        search_queries: List[str] = None,
    ) -> List[NewsArticle]:
        """
        Fetch news from all available Google sources.
        
        Args:
            session: aiohttp session
            topic: Main topic for RSS feeds
            search_queries: Additional search queries
        
        Returns:
            Combined list of articles from all sources
        """
        all_articles = []
        tasks = []
        
        # RSS feeds
        tasks.append(self.fetch_rss_feeds(session, topics=[topic]))
        
        # Search queries
        if search_queries:
            for query in search_queries[:3]:  # Limit to save API quota
                tasks.append(self.search(session, query))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
        
        # Deduplicate
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        return unique_articles
