"""
Bing News API Integration Module.

Provides access to Bing News Search API (Azure Cognitive Services):
- Real-time news search
- Trending news
- Category-based news
- Publisher-specific queries

Requires Azure subscription with Bing Search v7 API enabled.
Free tier: 1000 queries/month

Usage:
    client = BingNewsClient()
    
    # Search news
    articles = await client.search(session, "artificial intelligence")
    
    # Get trending
    articles = await client.get_trending(session)
    
    # Get by category
    articles = await client.get_by_category(session, "Technology")
"""

import asyncio
import hashlib
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class BingNewsArticle:
    """Normalized article structure from Bing News."""
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
            "source_api": "bing",
        }


# =============================================================================
# BING NEWS CLIENT
# =============================================================================

class BingNewsClient:
    """
    Bing News Search API client (Azure Cognitive Services).
    
    Features:
    - Real-time news search
    - Freshness filter (Day, Week, Month)
    - Category browsing
    - Trending topics
    - Market/language localization
    
    Requires BING_API_KEY environment variable.
    """
    
    # API endpoints
    SEARCH_URL = "https://api.bing.microsoft.com/v7.0/news/search"
    TRENDING_URL = "https://api.bing.microsoft.com/v7.0/news/trendingtopics"
    CATEGORY_URL = "https://api.bing.microsoft.com/v7.0/news"
    
    # News categories supported by Bing
    CATEGORIES = [
        "Business",
        "Entertainment",
        "Health",
        "Politics",
        "ScienceAndTechnology",
        "Sports",
        "US",
        "World",
    ]
    
    # Freshness options
    FRESHNESS = {
        "hour": "Hour",       # Last hour
        "day": "Day",         # Last 24 hours
        "week": "Week",       # Last 7 days
        "month": "Month",     # Last 30 days
    }
    
    def __init__(self, api_key: str = ""):
        """
        Initialize Bing News client.
        
        Args:
            api_key: Bing Search API key (uses settings if not provided)
        """
        # Try to load from settings if not provided
        if not api_key:
            try:
                from config.settings import BING_API_KEY
                api_key = BING_API_KEY
            except ImportError:
                pass
        
        self._api_key = api_key
        self._enabled = bool(api_key)
        
        if not self._enabled:
            logger.warning(
                "Bing News API not configured. "
                "Set BING_API_KEY in .env"
            )
        
        # Rate limiting
        self._request_count = 0
        self._last_reset = datetime.now(UTC)
    
    @property
    def is_enabled(self) -> bool:
        """Check if API is configured."""
        return self._enabled
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers."""
        return {
            "Ocp-Apim-Subscription-Key": self._api_key,
            "Accept": "application/json",
        }
    
    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
        count: int = 20,
        freshness: str = "Day",
        market: str = "en-US",
        sort_by: str = "Date",  # Date or Relevance
    ) -> List[BingNewsArticle]:
        """
        Search Bing News for articles.
        
        Args:
            session: aiohttp session
            query: Search query
            count: Number of results (max 100)
            freshness: Time filter (Hour, Day, Week, Month)
            market: Market/locale code
            sort_by: Sort order (Date or Relevance)
        
        Returns:
            List of news articles
        """
        if not self._enabled:
            logger.debug("Bing News API not enabled, skipping search")
            return []
        
        articles = []
        
        try:
            params = {
                "q": query,
                "count": min(count, 100),
                "freshness": freshness,
                "mkt": market,
                "sortBy": sort_by,
                "textDecorations": False,
                "textFormat": "Raw",
            }
            
            async with session.get(
                self.SEARCH_URL,
                headers=self._get_headers(),
                params=params,
                timeout=15,
            ) as response:
                if response.status == 401:
                    logger.error("Bing API authentication failed - check API key")
                    return articles
                    
                if response.status == 429:
                    logger.warning("Bing API rate limit exceeded")
                    return articles
                
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"Bing News API error {response.status}: {error}")
                    return articles
                
                data = await response.json()
                self._request_count += 1
                
                for item in data.get("value", []):
                    article = self._parse_article(item)
                    if article:
                        articles.append(article)
                
                logger.info(f"Bing News: {len(articles)} results for '{query}'")
                
        except asyncio.TimeoutError:
            logger.warning("Bing News API timeout")
        except Exception as e:
            logger.error(f"Bing News API error: {e}")
        
        return articles
    
    async def get_trending(
        self,
        session: aiohttp.ClientSession,
        market: str = "en-US",
        count: int = 20,
    ) -> List[BingNewsArticle]:
        """
        Get trending news topics.
        
        Args:
            session: aiohttp session
            market: Market/locale code
            count: Number of trending topics to return
        
        Returns:
            List of trending news articles
        """
        if not self._enabled:
            return []
        
        articles = []
        
        try:
            params = {
                "mkt": market,
                "count": count,
            }
            
            async with session.get(
                self.TRENDING_URL,
                headers=self._get_headers(),
                params=params,
                timeout=15,
            ) as response:
                if response.status != 200:
                    logger.warning(f"Bing Trending API error: {response.status}")
                    return articles
                
                data = await response.json()
                self._request_count += 1
                
                for item in data.get("value", []):
                    article = self._parse_trending(item)
                    if article:
                        articles.append(article)
                
                logger.info(f"Bing Trending: {len(articles)} topics")
                
        except Exception as e:
            logger.error(f"Bing Trending API error: {e}")
        
        return articles
    
    async def get_by_category(
        self,
        session: aiohttp.ClientSession,
        category: str = "ScienceAndTechnology",
        market: str = "en-US",
    ) -> List[BingNewsArticle]:
        """
        Get news by category.
        
        Args:
            session: aiohttp session
            category: News category (ScienceAndTechnology, Business, etc.)
            market: Market/locale code
        
        Returns:
            List of category news articles
        """
        if not self._enabled:
            return []
        
        # Validate category
        if category not in self.CATEGORIES:
            logger.warning(f"Unknown category: {category}. Using ScienceAndTechnology")
            category = "ScienceAndTechnology"
        
        articles = []
        
        try:
            params = {
                "category": category,
                "mkt": market,
            }
            
            async with session.get(
                self.CATEGORY_URL,
                headers=self._get_headers(),
                params=params,
                timeout=15,
            ) as response:
                if response.status != 200:
                    logger.warning(f"Bing Category API error: {response.status}")
                    return articles
                
                data = await response.json()
                self._request_count += 1
                
                for item in data.get("value", []):
                    article = self._parse_article(item)
                    if article:
                        article.category = category
                        articles.append(article)
                
                logger.info(f"Bing Category '{category}': {len(articles)} articles")
                
        except Exception as e:
            logger.error(f"Bing Category API error: {e}")
        
        return articles
    
    def _parse_article(self, item: Dict) -> Optional[BingNewsArticle]:
        """Parse a Bing News search result."""
        try:
            url = item.get("url", "")
            if not url:
                return None
            
            article_id = hashlib.md5(url.encode()).hexdigest()
            
            # Parse publication date
            published_at = None
            date_str = item.get("datePublished")
            if date_str:
                try:
                    # Bing uses ISO 8601 format
                    published_at = datetime.fromisoformat(
                        date_str.replace("Z", "+00:00")
                    )
                except Exception as e:
                    logger.debug(f"_parse_article: suppressed {type(e).__name__}: {e}")
            
            # Extract source
            provider = item.get("provider", [{}])
            source = provider[0].get("name", "Unknown") if provider else "Unknown"
            
            # Extract image
            image_url = ""
            image = item.get("image", {})
            if image:
                thumbnail = image.get("thumbnail", {})
                image_url = thumbnail.get("contentUrl", "")
            
            return BingNewsArticle(
                id=article_id,
                title=item.get("name", ""),
                url=url,
                source=source,
                published_at=published_at,
                description=item.get("description", ""),
                image_url=image_url,
                category=item.get("category", ""),
            )
            
        except Exception as e:
            logger.debug(f"Error parsing Bing article: {e}")
            return None
    
    def _parse_trending(self, item: Dict) -> Optional[BingNewsArticle]:
        """Parse a Bing trending topic."""
        try:
            query = item.get("query", {})
            title = query.get("text", "")
            url = item.get("webSearchUrl", "")
            
            if not title or not url:
                return None
            
            article_id = hashlib.md5(title.encode()).hexdigest()
            
            return BingNewsArticle(
                id=article_id,
                title=title,
                url=url,
                source="Bing Trending",
                description=item.get("description", ""),
                image_url=item.get("image", {}).get("url", ""),
            )
            
        except Exception as e:
            logger.debug(f"Error parsing Bing trending: {e}")
            return None
    
    async def fetch_all_tech_news(
        self,
        session: aiohttp.ClientSession,
        queries: List[str] = None,
    ) -> List[BingNewsArticle]:
        """
        Fetch all technology news from multiple sources.
        
        Args:
            session: aiohttp session
            queries: Additional search queries
        
        Returns:
            Combined list of tech news articles
        """
        if not self._enabled:
            return []
        
        all_articles = []
        tasks = []
        
        # Category: ScienceAndTechnology
        tasks.append(self.get_by_category(session, "ScienceAndTechnology"))
        
        # Trending topics
        tasks.append(self.get_trending(session))
        
        # Default tech queries
        default_queries = queries or [
            "artificial intelligence",
            "tech news today",
            "startup funding",
        ]
        
        for query in default_queries[:3]:  # Limit to save quota
            tasks.append(self.search(session, query, freshness="Day"))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"Bing fetch error: {result}")
        
        # Deduplicate by URL
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        logger.info(f"Bing News total: {len(unique_articles)} unique articles")
        return unique_articles
    
    def get_stats(self) -> Dict[str, Any]:
        """Get API usage statistics."""
        return {
            "enabled": self._enabled,
            "requests_made": self._request_count,
            "last_reset": self._last_reset.isoformat(),
        }
