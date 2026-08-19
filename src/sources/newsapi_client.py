"""
NewsAPI.org Integration Module.

Provides access to 70,000+ news sources worldwide:
- Top headlines by country/category
- Everything search (full archive)
- Source listing

Free tier: 100 requests/day, articles limited to 1 month old
Paid: $449/mo for real-time access

Usage:
    client = NewsAPIClient()
    
    # Get top headlines
    articles = await client.get_top_headlines(session, country="us")
    
    # Search everything
    articles = await client.search(session, "artificial intelligence")
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class NewsAPIArticle:
    """Normalized article structure from NewsAPI."""
    id: str
    title: str
    url: str
    source: str
    source_id: str = ""
    published_at: Optional[datetime] = None
    description: str = ""
    content: str = ""
    image_url: str = ""
    author: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_id": self.source_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "description": self.description,
            "content": self.content,
            "image_url": self.image_url,
            "author": self.author,
            "source_api": "newsapi",
        }


class NewsAPIClient:
    """
    NewsAPI.org client for accessing 70,000+ news sources.
    
    Endpoints:
    - Top Headlines: Breaking news by country/category
    - Everything: Full-text search across sources
    - Sources: List available news sources
    
    Rate limits:
    - Free: 100 requests/day, 1-month article age limit
    - Paid: Higher limits, real-time access
    """
    
    BASE_URL = "https://newsapi.org/v2"
    
    # Categories supported by NewsAPI
    CATEGORIES = [
        "business",
        "entertainment",
        "general",
        "health",
        "science",
        "sports",
        "technology",
    ]
    
    def __init__(self, api_key: str = ""):
        """
        Initialize NewsAPI client.
        
        Args:
            api_key: NewsAPI key (uses settings if not provided)
        """
        if not api_key:
            try:
                from config.settings import NEWSAPI_KEY
                api_key = NEWSAPI_KEY
            except ImportError:
                pass
        
        self._api_key = api_key
        self._enabled = bool(api_key)
        
        if not self._enabled:
            logger.warning("NewsAPI not configured. Set NEWSAPI_KEY in .env")
        
        self._request_count = 0
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
    
    async def get_top_headlines(
        self,
        session: aiohttp.ClientSession,
        country: str = "us",
        category: str = "technology",
        page_size: int = 20,
    ) -> List[NewsAPIArticle]:
        """
        Get top headlines.
        
        Args:
            session: aiohttp session
            country: Country code (us, gb, in, etc.)
            category: News category
            page_size: Number of results
        
        Returns:
            List of headline articles
        """
        if not self._enabled:
            return []
        
        articles = []
        
        try:
            params = {
                "country": country,
                "category": category,
                "pageSize": min(page_size, 100),
                "apiKey": self._api_key,
            }
            
            url = f"{self.BASE_URL}/top-headlines"
            async with session.get(url, params=params, timeout=15) as response:
                if response.status == 401:
                    logger.error("NewsAPI authentication failed")
                    return articles
                
                if response.status == 429:
                    logger.warning("NewsAPI rate limit exceeded")
                    return articles
                
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"NewsAPI error {response.status}: {error}")
                    return articles
                
                data = await response.json()
                self._request_count += 1
                
                if data.get("status") != "ok":
                    logger.warning(f"NewsAPI status: {data.get('status')}")
                    return articles
                
                for item in data.get("articles", []):
                    article = self._parse_article(item)
                    if article:
                        articles.append(article)
                
                logger.info(f"NewsAPI headlines: {len(articles)} articles")
                
        except asyncio.TimeoutError:
            logger.warning("NewsAPI timeout")
        except Exception as e:
            logger.error(f"NewsAPI error: {e}")
        
        return articles
    
    async def search(
        self,
        session: aiohttp.ClientSession,
        query: str,
        sort_by: str = "publishedAt",  # relevancy, popularity, publishedAt
        from_date: Optional[datetime] = None,
        page_size: int = 20,
    ) -> List[NewsAPIArticle]:
        """
        Search all articles.
        
        Args:
            session: aiohttp session
            query: Search query
            sort_by: Sort order
            from_date: Start date for search
            page_size: Number of results
        
        Returns:
            List of matching articles
        """
        if not self._enabled:
            return []
        
        articles = []
        
        try:
            # Default to last 7 days
            if not from_date:
                from_date = datetime.now(UTC) - timedelta(days=7)
            
            params = {
                "q": query,
                "sortBy": sort_by,
                "from": from_date.strftime("%Y-%m-%d"),
                "pageSize": min(page_size, 100),
                "apiKey": self._api_key,
            }
            
            url = f"{self.BASE_URL}/everything"
            async with session.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    logger.warning(f"NewsAPI search error: {response.status}")
                    return articles
                
                data = await response.json()
                self._request_count += 1
                
                for item in data.get("articles", []):
                    article = self._parse_article(item)
                    if article:
                        articles.append(article)
                
                logger.info(f"NewsAPI search '{query}': {len(articles)} articles")
                
        except Exception as e:
            logger.error(f"NewsAPI search error: {e}")
        
        return articles
    
    def _parse_article(self, item: Dict) -> Optional[NewsAPIArticle]:
        """Parse a NewsAPI article."""
        try:
            url = item.get("url", "")
            if not url or "[Removed]" in item.get("title", ""):
                return None
            
            article_id = hashlib.md5(url.encode()).hexdigest()
            
            # Parse date
            published_at = None
            date_str = item.get("publishedAt")
            if date_str:
                try:
                    published_at = datetime.fromisoformat(
                        date_str.replace("Z", "+00:00")
                    )
                except Exception as e:
                    logger.warning(f"_parse_article: suppressed {type(e).__name__}: {e}")
            
            source = item.get("source", {})
            
            return NewsAPIArticle(
                id=article_id,
                title=item.get("title", ""),
                url=url,
                source=source.get("name", "Unknown"),
                source_id=source.get("id", ""),
                published_at=published_at,
                description=item.get("description", ""),
                content=item.get("content", ""),
                image_url=item.get("urlToImage", ""),
                author=item.get("author", ""),
            )
            
        except Exception as e:
            logger.debug(f"Error parsing NewsAPI article: {e}")
            return None
    
    async def fetch_tech_news(
        self,
        session: aiohttp.ClientSession,
    ) -> List[NewsAPIArticle]:
        """Fetch all technology news."""
        if not self._enabled:
            return []
        
        all_articles = []
        tasks = [
            self.get_top_headlines(session, category="technology"),
            self.search(session, "artificial intelligence"),
            self.search(session, "startup funding technology"),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
        
        # Deduplicate
        seen = set()
        unique = []
        for a in all_articles:
            if a.url not in seen:
                seen.add(a.url)
                unique.append(a)
        
        return unique
