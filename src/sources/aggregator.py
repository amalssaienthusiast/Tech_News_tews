"""
Unified Discovery Aggregator.

Combines all news discovery sources into a single interface:
- Google News (RSS + API)
- Bing News API
- NewsAPI.org
- Existing RSS feeds

Provides:
- Unified article format
- Automatic source selection based on availability
- Deduplication across sources
- Rate limit management

Usage:
    aggregator = DiscoveryAggregator()
    
    async with aiohttp.ClientSession() as session:
        articles = await aggregator.discover_all(session, topics=["AI", "tech"])
"""

import asyncio
import hashlib
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field

import aiohttp

from src.sources.google_news import GoogleNewsClient, NewsArticle as GoogleArticle
from src.sources.bing_news import BingNewsClient, BingNewsArticle
from src.sources.newsapi_client import NewsAPIClient, NewsAPIArticle
from src.discovery.global_discovery import get_global_discovery_manager

# DuckDuckGo removed — it returned undated, low-quality web search results
# that flooded the feed and blocked the async event loop (time.sleep in rate limiter).
DUCKDUCKGO_AVAILABLE = False

try:
    from src.sources.reddit_client import RedditClient, RedditPost
    REDDIT_AVAILABLE = True
except ImportError:
    REDDIT_AVAILABLE = False

try:
    from src.sources.google_trends import GoogleTrendsClient
    TRENDS_AVAILABLE = True
except ImportError:
    TRENDS_AVAILABLE = False

try:
    from src.sources.twitter_client import TwitterClient, Tweet
    TWITTER_AVAILABLE = True
except ImportError:
    TWITTER_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# UNIFIED ARTICLE FORMAT
# =============================================================================

@dataclass
class UnifiedArticle:
    """
    Unified article format across all discovery sources.
    
    Normalizes articles from Google News, Bing News, NewsAPI, and RSS feeds
    into a single consistent structure for the real-time feeder.
    """
    id: str
    title: str
    url: str
    source: str
    source_api: str  # google, bing, newsapi, rss
    published_at: Optional[datetime] = None
    description: str = ""
    content: str = ""
    image_url: str = ""
    author: str = ""
    category: str = ""
    topics: List[str] = field(default_factory=list)
    score: float = 0.0  # Relevance/quality score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/transmission."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_api": self.source_api,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "description": self.description,
            "content": self.content,
            "image_url": self.image_url,
            "author": self.author,
            "category": self.category,
            "topics": self.topics,
            "score": self.score,
        }
    
    @classmethod
    def from_google(cls, article: GoogleArticle) -> "UnifiedArticle":
        """Convert Google News article to unified format."""
        return cls(
            id=article.id,
            title=article.title,
            url=article.url,
            source=article.source,
            source_api="google",
            published_at=article.published_at,
            description=article.description,
            image_url=article.image_url,
            category=article.category,
            topics=article.topics,
        )
    
    @classmethod
    def from_bing(cls, article: BingNewsArticle) -> "UnifiedArticle":
        """Convert Bing News article to unified format."""
        return cls(
            id=article.id,
            title=article.title,
            url=article.url,
            source=article.source,
            source_api="bing",
            published_at=article.published_at,
            description=article.description,
            image_url=article.image_url,
            category=article.category,
            topics=article.topics,
        )
    
    @classmethod
    def from_newsapi(cls, article: NewsAPIArticle) -> "UnifiedArticle":
        """Convert NewsAPI article to unified format."""
        return cls(
            id=article.id,
            title=article.title,
            url=article.url,
            source=article.source,
            source_api="newsapi",
            published_at=article.published_at,
            description=article.description,
            content=article.content,
            image_url=article.image_url,
            author=article.author,
        )


# =============================================================================
# DISCOVERY AGGREGATOR
# =============================================================================

class DiscoveryAggregator:
    """
    Unified discovery aggregator combining all news sources.
    
    Features:
    - Automatic source selection based on API availability
    - Parallel fetching from multiple sources
    - Cross-source deduplication
    - Configurable source priorities
    - Rate limit management
    """
    
    def __init__(
        self,
        enable_google: bool = True,
        enable_bing: bool = True,
        enable_newsapi: bool = True,
    ):
        """
        Initialize discovery aggregator.
        
        Args:
            enable_google: Enable Google News sources
            enable_bing: Enable Bing News API
            enable_newsapi: Enable NewsAPI.org
        """
        self._google = GoogleNewsClient() if enable_google else None
        self._bing = BingNewsClient() if enable_bing else None
        self._newsapi = NewsAPIClient() if enable_newsapi else None
        
        # Geo-rotation manager for multi-region news discovery (Silicon Valley, India, Japan, UK, Germany, etc.)
        self._geo_manager = get_global_discovery_manager(rotation_interval=120)
        
        # New sources (always enabled if available)
        self._duckduckgo = None  # Disabled: low-quality, undated results
        self._reddit = RedditClient() if REDDIT_AVAILABLE else None
        self._trends = GoogleTrendsClient() if TRENDS_AVAILABLE else None
        self._twitter = TwitterClient() if TWITTER_AVAILABLE else None
        
        # Track seen URLs for deduplication
        self._seen_urls: Set[str] = set()
        
        # Statistics
        self._stats = {
            "google_articles": 0,
            "bing_articles": 0,
            "newsapi_articles": 0,
            "duckduckgo_articles": 0,
            "reddit_posts": 0,
            "twitter_tweets": 0,
            "duplicates_filtered": 0,
            "total_discovered": 0,
        }
    
    def get_available_sources(self) -> List[str]:
        """Get list of available (enabled and configured) sources."""
        sources = []
        
        if self._google:
            sources.append("google_rss")  # Always available
            if self._google.api_enabled:
                sources.append("google_api")
        
        if self._bing and self._bing.is_enabled:
            sources.append("bing")
        
        if self._newsapi and self._newsapi.is_enabled:
            sources.append("newsapi")
        
        # DuckDuckGo disabled — low-quality undated results
        
        if self._reddit:
            sources.append("reddit")
        
        if self._trends:
            sources.append("google_trends")
        
        if self._twitter and self._twitter.is_available:
            sources.append("twitter")
        
        return sources
    
    async def discover_all(
        self,
        session: aiohttp.ClientSession,
        topics: List[str] = None,
        queries: List[str] = None,
        max_per_source: int = 50,
    ) -> List[UnifiedArticle]:
        """
        Discover articles from all available sources.
        
        Args:
            session: aiohttp session
            topics: Topic categories to fetch
            queries: Search queries to run
            max_per_source: Maximum articles per source
        
        Returns:
            Unified list of articles from all sources
        """
        topics = topics or ["technology", "business", "science", "world"]

        # Rotate active tech hub region (e.g. US, IN, JP, GB, DE, CN, TW, KR, IL, SG, AU, CA, FR, SE)
        hub = self._geo_manager.get_current_hub()
        logger.info(f"🌍 Discovery pass targeting tech hub: {hub.name} ({hub.code}) [Lang: {hub.language}]")
        self._geo_manager._rotate_to_next()
        
        # Advanced keyword permutations for deep searches
        default_queries = [
            "breaking technology news",
            "artificial intelligence updates",
            "cybersecurity breach",
            "startup funding rounds",
            "tech layoffs",
            "new gadget releases",
            "cloud computing innovations",
            "open source software releases"
        ]
        queries = queries if queries else default_queries  # Treat empty list same as None
        
        all_articles: List[UnifiedArticle] = []
        tasks = []
        
        # Google News (RSS is always available)
        if self._google:
            tasks.append(self._fetch_google(session, topics, queries, hub.code.lower()))
        
        # Bing News (requires API key)
        if self._bing and self._bing.is_enabled:
            tasks.append(self._fetch_bing(session, queries))
        
        # NewsAPI (requires API key)
        if self._newsapi and self._newsapi.is_enabled:
            tasks.append(self._fetch_newsapi(session))
        
        # DuckDuckGo disabled — produced undated, low-quality results
        
        # Reddit (no API key needed)
        if self._reddit:
            tasks.append(self._fetch_reddit(session))
        
        # Twitter (requires bearer token)
        if self._twitter and self._twitter.is_available:
            tasks.append(self._fetch_twitter())
        
        if not tasks:
            logger.warning("No discovery sources available")
            return []
        
        # Fetch from all sources in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Discovery task error: {result}")
        
        # Deduplicate across sources
        unique_articles = self._deduplicate(all_articles)
        
        # Sort by publication date (newest first)
        unique_articles.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        
        self._stats["total_discovered"] = len(unique_articles)
        self._geo_manager.update_stats(hub.code, len(unique_articles))
        logger.info(f"✓ Discovery pass complete ({hub.code}): {len(unique_articles)} unique articles found across sources")
        
        return unique_articles
    
    async def _fetch_google(
        self,
        session: aiohttp.ClientSession,
        topics: List[str],
        queries: List[str],
        region: str = "us",
    ) -> List[UnifiedArticle]:
        """Fetch from Google News sources for the active region."""
        articles = []
        
        try:
            # Use geo-localized Google News client for active region
            google_client = GoogleNewsClient(region=region)
            
            # Fetch RSS feeds for topics
            google_articles = await google_client.fetch_rss_feeds(
                session,
                topics=topics,
                include_headlines=False,  # Disabled: top headlines are general news, not tech/science
            )
            
            # Also search for specific queries
            for query in queries[:2]:
                search_results = await google_client.search(session, query)
                google_articles.extend(search_results)
            
            # Convert to unified format
            for ga in google_articles:
                articles.append(UnifiedArticle.from_google(ga))
            
            self._stats["google_articles"] = len(articles)
            
        except Exception as e:
            logger.error(f"Google News fetch error: {e}")
        
        return articles
    
    async def _fetch_bing(
        self,
        session: aiohttp.ClientSession,
        queries: List[str],
    ) -> List[UnifiedArticle]:
        """Fetch from Bing News API."""
        articles = []
        
        try:
            bing_articles = await self._bing.fetch_all_tech_news(
                session,
                queries=queries,
            )
            
            for ba in bing_articles:
                articles.append(UnifiedArticle.from_bing(ba))
            
            self._stats["bing_articles"] = len(articles)
            
        except Exception as e:
            logger.error(f"Bing News fetch error: {e}")
        
        return articles
    
    async def _fetch_newsapi(
        self,
        session: aiohttp.ClientSession,
    ) -> List[UnifiedArticle]:
        """Fetch from NewsAPI.org."""
        articles = []
        
        try:
            newsapi_articles = await self._newsapi.fetch_tech_news(session)
            
            for na in newsapi_articles:
                articles.append(UnifiedArticle.from_newsapi(na))
            
            self._stats["newsapi_articles"] = len(articles)
            
        except Exception as e:
            logger.error(f"NewsAPI fetch error: {e}")
        
        return articles
    
    async def _fetch_duckduckgo(
        self,
        session: aiohttp.ClientSession,
        queries: List[str],
    ) -> List[UnifiedArticle]:
        """Fetch from DuckDuckGo search."""
        articles = []
        
        try:
            ddg_articles = await self._duckduckgo.search(session, queries=queries)
            
            for da in ddg_articles:
                articles.append(UnifiedArticle(
                    id=da.id,
                    title=da.title,
                    url=da.url,
                    source=da.source,
                    source_api="duckduckgo",
                    description=da.description,
                    published_at=da.published_at,
                ))
            
            self._stats["duckduckgo_articles"] = len(articles)
            logger.info(f"DuckDuckGo: {len(articles)} articles")
            
        except Exception as e:
            logger.error(f"DuckDuckGo fetch error: {e}")
        
        return articles
    
    async def _fetch_reddit(
        self,
        session: aiohttp.ClientSession,
    ) -> List[UnifiedArticle]:
        """Fetch from Reddit tech subreddits."""
        articles = []
        
        try:
            reddit_posts = await self._reddit.fetch_posts(session, sort="hot", limit=20)
            
            for post in reddit_posts:
                # Convert Reddit post to unified article
                articles.append(UnifiedArticle(
                    id=post.id,
                    title=post.title,
                    url=post.external_url,  # External link or Reddit URL
                    source=f"r/{post.subreddit}",
                    source_api="reddit",
                    description=post.selftext[:200] if post.selftext else "",
                    published_at=post.created_utc,
                    score=float(post.score),  # Use Reddit upvotes as score
                ))
            
            self._stats["reddit_posts"] = len(articles)
            logger.info(f"Reddit: {len(articles)} posts")
            
        except Exception as e:
            logger.error(f"Reddit fetch error: {e}")
        
        return articles
    
    async def _fetch_twitter(self) -> List[UnifiedArticle]:
        """Fetch from Twitter/X tech news accounts."""
        articles = []
        
        try:
            tweets = await self._twitter.search_tech_news()
            
            for tweet in tweets:
                # Convert Tweet to unified article
                articles.append(UnifiedArticle(
                    id=f"tw_{tweet.id}",
                    title=tweet._extract_title(),
                    url=tweet.url,
                    source=f"Twitter/@{tweet.author_username}",
                    source_api="twitter",
                    description=tweet.text[:300],
                    published_at=tweet.created_at,
                    author=tweet.author_name or tweet.author_username,
                    score=tweet.engagement_score,
                    topics=tweet.hashtags,
                ))
            
            self._stats["twitter_tweets"] = len(articles)
            logger.info(f"Twitter: {len(articles)} tweets")
            
        except Exception as e:
            logger.error(f"Twitter fetch error: {e}")
        
        return articles
    
    def _deduplicate(
        self,
        articles: List[UnifiedArticle],
    ) -> List[UnifiedArticle]:
        """
        Deduplicate articles across sources.
        
        Uses URL-based deduplication with normalization.
        """
        unique = []
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()
        
        for article in articles:
            # Normalize URL
            url = article.url.lower().rstrip("/")
            
            # Skip if URL already seen
            if url in seen_urls:
                self._stats["duplicates_filtered"] += 1
                continue
            
            # Also check for similar titles (different URLs, same story)
            title_key = self._normalize_title(article.title)
            if title_key in seen_titles and len(title_key) > 20:
                self._stats["duplicates_filtered"] += 1
                continue
            
            seen_urls.add(url)
            seen_titles.add(title_key)
            unique.append(article)
        
        return unique
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        import re
        # Remove punctuation and lowercase
        normalized = re.sub(r"[^\w\s]", "", title.lower())
        # Remove extra whitespace
        normalized = " ".join(normalized.split())
        return normalized
    
    def get_stats(self) -> Dict[str, Any]:
        """Get discovery statistics."""
        return {
            **self._stats,
            "available_sources": self.get_available_sources(),
        }
    
    def clear_cache(self) -> None:
        """Clear URL deduplication cache."""
        self._seen_urls.clear()
        self._stats["duplicates_filtered"] = 0
    
    async def close(self) -> None:
        """
        Gracefully close aggregator resources.
        
        Called during shutdown to clean up any open connections
        or sessions held by the aggregator's clients.
        """
        # Close Reddit client if it has a close method
        if self._reddit and hasattr(self._reddit, 'close'):
            try:
                if asyncio.iscoroutinefunction(self._reddit.close):
                    await self._reddit.close()
                else:
                    self._reddit.close()
            except Exception as e:
                logger.debug(f"Error closing Reddit client: {e}")
        
        # Close Twitter client if it has a close method
        if self._twitter and hasattr(self._twitter, 'close'):
            try:
                if asyncio.iscoroutinefunction(self._twitter.close):
                    await self._twitter.close()
                else:
                    self._twitter.close()
            except Exception as e:
                logger.debug(f"Error closing Twitter client: {e}")
        
        # Clear caches
        self._seen_urls.clear()
        
        logger.info("DiscoveryAggregator closed")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def discover_tech_news(
    session: aiohttp.ClientSession = None,
    topics: List[str] = None,
) -> List[UnifiedArticle]:
    """
    Convenience function to discover tech news from all sources.
    
    Args:
        session: Optional aiohttp session (creates one if not provided)
        topics: Optional list of topics
    
    Returns:
        List of discovered articles
    """
    aggregator = DiscoveryAggregator()
    
    if session:
        return await aggregator.discover_all(session, topics=topics)
    
    async with aiohttp.ClientSession() as new_session:
        return await aggregator.discover_all(new_session, topics=topics)
