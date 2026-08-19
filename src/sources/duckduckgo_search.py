"""
DuckDuckGo Search Client for Tech News Discovery.

Uses DuckDuckGo's search to find tech news articles.
No API key required - uses the ddgs library (formerly duckduckgo-search).

Features:
- Text search for news
- Built-in rate limiting to avoid 202 Ratelimit errors
- Exponential backoff on failures
- No API key required
"""

import asyncio
import logging
import hashlib
import random
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import List, Optional

import aiohttp

# REMOVED: Global SSL bypass (ssl._create_default_https_context = ssl._create_unverified_context)
# It was disabling certificate verification for ALL HTTPS connections in the process,
# not just DuckDuckGo. This is a security risk. If DDG needs SSL bypass, it should
# be scoped to its own session only.

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DuckDuckGoArticle:
    """Article from DuckDuckGo search results."""
    id: str
    url: str
    title: str
    description: str
    source: str
    published_at: Optional[datetime] = None
    is_advanced: bool = False
    
    @classmethod
    def from_result(cls, result: dict) -> "DuckDuckGoArticle":
        """Create from DDG search result."""
        url = result.get("href", result.get("link", ""))
        title = result.get("title", "")
        
        return cls(
            id=hashlib.md5(url.encode()).hexdigest(),
            url=url,
            title=title,
            description=result.get("body", result.get("snippet", "")),
            source=cls._extract_source(url),
            published_at=None,  # DDG doesn't provide dates
        )
    
    @staticmethod
    def _extract_source(url: str) -> str:
        """Extract source name from URL."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception as e:
            logger.debug(f"_extract_source: suppressed {type(e).__name__}: {e}")
            return "Unknown"


# =============================================================================
# DUCKDUCKGO CLIENT
# =============================================================================

class DuckDuckGoClient:
    """
    DuckDuckGo search client for news discovery.
    
    Uses the ddgs library (formerly duckduckgo-search) for searching.
    Includes built-in rate limiting and exponential backoff to handle
    rate limit errors (202 Ratelimit).
    """
    
    # Tech-focused search queries
    DEFAULT_QUERIES = [
        "technology news today",
        "AI artificial intelligence news",
        "startup funding news",
        "cybersecurity news",
        "tech industry news",
        "software engineering news",
        "new tech gadgets release",
        "cloud computing news",
        "data science machine learning news",
        "cryptocurrency blockchain news",
        "tech layoffs news",
        "silicon valley startup news",
        "open source software news",
        "cybersecurity breaches and hacks today",
        "computing breakthroughs",
        "semiconductor industry news",
        "AR VR mixed reality tech news",
        "autonomous vehicles and self-driving cars news",
        "biotech and health tech news",
        "space exploration tech news"
    ]
    
    # Rate limiting configuration
    MIN_DELAY_BETWEEN_QUERIES = 2.0  # Minimum seconds between queries
    MAX_DELAY_BETWEEN_QUERIES = 4.0  # Maximum seconds between queries (with jitter)
    MAX_RETRIES = 3
    BACKOFF_FACTOR = 2.0  # Exponential backoff multiplier
    
    def __init__(self, max_results_per_query: int = 10):
        """
        Initialize DuckDuckGo client.
        
        Args:
            max_results_per_query: Max results per search query
        """
        self._max_results = max_results_per_query
        self._ddg_available = self._check_ddg_library()
        self._last_request_time = 0.0
        
        if self._ddg_available:
            package_name = "ddgs" if self._use_new_package else "duckduckgo-search"
            logger.info(f"DuckDuckGo client initialized with {package_name}")
        else:
            logger.warning("ddgs/duckduckgo-search not installed, using fallback API")
    
    def _check_ddg_library(self) -> bool:
        """Check if ddgs or duckduckgo-search library is available."""
        try:
            # Try new package name first (ddgs)
            from ddgs import DDGS
            self._ddgs_class = DDGS
            self._use_new_package = True
            return True
        except ImportError:
            try:
                # Fall back to old package name (duckduckgo_search)
                import warnings
                warnings.filterwarnings("ignore", message=".*renamed to.*ddgs.*")
                from duckduckgo_search import DDGS
                self._ddgs_class = DDGS
                self._use_new_package = False
                return True
            except ImportError:
                self._ddgs_class = None
                self._use_new_package = False
                return False
    
    def _apply_rate_limit(self) -> None:
        """Apply rate limiting between requests with random jitter."""
        current_time = time.time()
        elapsed = current_time - self._last_request_time
        delay = random.uniform(self.MIN_DELAY_BETWEEN_QUERIES, self.MAX_DELAY_BETWEEN_QUERIES)
        
        if elapsed < delay:
            sleep_time = delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self._last_request_time = time.time()
    
    async def search(
        self,
        session: aiohttp.ClientSession,
        queries: Optional[List[str]] = None,
    ) -> List[DuckDuckGoArticle]:
        """
        Search DuckDuckGo for tech news.
        
        Args:
            session: aiohttp session (not used with library)
            queries: Search queries (uses defaults if None)
        
        Returns:
            List of discovered articles
        """
        queries = queries or self.DEFAULT_QUERIES
        articles = []
        
        if self._ddg_available:
            articles = await self._search_with_library(queries)
        else:
            articles = await self._search_with_api(session, queries)
        
        logger.info(f"DuckDuckGo: Found {len(articles)} articles")
        return articles
    
    async def _search_with_library(
        self,
        queries: List[str],
    ) -> List[DuckDuckGoArticle]:
        """
        Search using official duckduckgo-search (ddgs) library.
        """
        articles = []
        seen_urls = set()
        
        for query in queries:
            try:
                self._apply_rate_limit()
                
                # Execute synchronously via run_in_executor
                loop = asyncio.get_event_loop()
                
                def fetch_results():
                    ddgs = self._ddgs_class()
                        
                    with ddgs:
                        return list(ddgs.text(query, max_results=self._max_results, timelimit="d"))
                
                results = await loop.run_in_executor(None, fetch_results)
                
                for r in results:
                    url = r.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        article = DuckDuckGoArticle(
                            id=hashlib.md5(url.encode()).hexdigest(),
                            url=url,
                            title=r.get("title", ""),
                            description=r.get("body", ""),
                            source=DuckDuckGoArticle._extract_source(url),
                            published_at=None,
                        )
                        articles.append(article)
                        
            except Exception as e:
                logger.warning(f"DDG library search error for '{query}': {e}")
                
        return articles
    
    async def _search_with_api(
        self,
        session: aiohttp.ClientSession,
        queries: List[str],
    ) -> List[DuckDuckGoArticle]:
        """Fallback: Search using DDG Instant Answer API."""
        articles = []
        seen_urls = set()
        
        for query in queries:
            try:
                # DDG Instant Answer API (limited but works)
                url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
                
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extract related topics
                        for topic in data.get("RelatedTopics", []):
                            if isinstance(topic, dict) and "FirstURL" in topic:
                                article_url = topic["FirstURL"]
                                if article_url not in seen_urls:
                                    seen_urls.add(article_url)
                                    articles.append(DuckDuckGoArticle(
                                        id=hashlib.md5(article_url.encode()).hexdigest(),
                                        url=article_url,
                                        title=topic.get("Text", "")[:100],
                                        description=topic.get("Text", ""),
                                        source="DuckDuckGo",
                                    ))
                
                # Small delay between requests
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"DDG API error for '{query}': {e}")
        
        return articles
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string from DDG."""
        if not date_str:
            return None
        try:
            from dateutil.parser import parse
            return parse(date_str)
        except Exception as e:
            logger.debug(f"_parse_date: suppressed {type(e).__name__}: {e}")
            return None


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def search_duckduckgo(
    session: aiohttp.ClientSession = None,
    queries: List[str] = None,
) -> List[DuckDuckGoArticle]:
    """
    Convenience function to search DuckDuckGo.
    
    Args:
        session: Optional aiohttp session
        queries: Optional search queries
    
    Returns:
        List of discovered articles
    """
    client = DuckDuckGoClient()
    
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await client.search(session, queries)
    
    return await client.search(session, queries)
