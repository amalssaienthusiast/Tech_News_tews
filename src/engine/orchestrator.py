"""
Main Orchestrator for the Tech News Scraper.

This module provides the central coordination layer that ties
together all components into a unified, high-performance
tech news scraping system.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timezone, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Local imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.types import (
    Article,
    QueryIntent,
    QueryResult,
    ScrapingResult,
    ScrapingStatus,
    Source,
    SourceTier,
    TechScore,
)
from src.core.exceptions import (
    NonTechQueryError,
    InvalidQueryError,
    TechScraperError,
)
from src.data_structures import (
    URLDeduplicator,
    SourcePriorityQueue,
    HTTPResponseCache,
)
from src.engine.query_engine import QueryEngine
from src.engine.deep_scraper import DeepScraper
from src.engine.url_analyzer import URLAnalyzer, URLAnalysisResult
from src.engine.realtime_feeder import RealtimeNewsFeeder

# Import enhanced feeder with discovery aggregator and deduplication
try:
    from src.engine.enhanced_feeder import EnhancedRealtimeFeeder
    ENHANCED_FEEDER_AVAILABLE = True
except ImportError:
    ENHANCED_FEEDER_AVAILABLE = False
from src.core.events import event_bus
from src.core.protocol import StatsUpdate, LogMessage, EventType, SourceStatus
from src.engine.quality_filter import SourceQualityFilter
from src.crawler import EnhancedWebCrawler, EnhancedCrawlConfig
from src.discovery import WebDiscoveryAgent

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """
    Result of a search operation.
    
    Attributes:
        query: Original query
        query_result: Query analysis result
        articles: Found articles
        total_sources_scraped: Number of sources scraped
        total_time_ms: Total time taken
        errors: Any errors encountered
    """
    query: str
    query_result: QueryResult
    articles: List[Article]
    total_sources_scraped: int
    total_time_ms: float
    errors: List[str] = field(default_factory=list)


# Premium tech news sources (Tier 1)
PREMIUM_SOURCES = [
    {
        "url": "https://techcrunch.com",
        "name": "TechCrunch",
        "tier": SourceTier.TIER_1,
    },
    {
        "url": "https://www.theverge.com",
        "name": "The Verge",
        "tier": SourceTier.TIER_1,
    },
    {
        "url": "https://arstechnica.com",
        "name": "Ars Technica",
        "tier": SourceTier.TIER_1,
    },
    {
        "url": "https://www.wired.com",
        "name": "Wired",
        "tier": SourceTier.TIER_1,
    },
    {
        "url": "https://www.technologyreview.com",
        "name": "MIT Technology Review",
        "tier": SourceTier.TIER_1,
    },
]

# High-quality tech sources (Tier 2)
QUALITY_SOURCES = [
    {
        "url": "https://news.ycombinator.com",
        "name": "Hacker News",
        "tier": SourceTier.TIER_2,
    },
    {
        "url": "https://www.engadget.com",
        "name": "Engadget",
        "tier": SourceTier.TIER_2,
    },
    {
        "url": "https://gizmodo.com",
        "name": "Gizmodo",
        "tier": SourceTier.TIER_2,
    },
    {
        "url": "https://venturebeat.com",
        "name": "VentureBeat",
        "tier": SourceTier.TIER_2,
    },
    {
        "url": "https://www.zdnet.com",
        "name": "ZDNet",
        "tier": SourceTier.TIER_2,
    },
]


class TechNewsOrchestrator:
    """
    Central orchestrator for the Tech News Scraper.
    
    Coordinates all components to provide a unified interface
    for intelligent tech news scraping with:
    
    - Query understanding and validation
    - Multi-source deep scraping
    - URL deep analysis
    - Source priority management
    - Result aggregation and ranking
    
    Example:
        orchestrator = TechNewsOrchestrator()
        
        # Search for tech news
        result = await orchestrator.search("artificial intelligence breakthroughs")
        for article in result.articles:
            print(f"- {article.title}")
        
        # Analyze specific URL
        analysis = await orchestrator.analyze_url("https://example.com/article")
        print(analysis.key_points)
    """
    
    def __init__(
        self,
        enable_cache: bool = True,
        max_concurrent_scrapes: int = 5,
    ) -> None:
        """
        Initialize the orchestrator.
        
        Args:
            enable_cache: Whether to enable response caching
            max_concurrent_scrapes: Maximum concurrent scraping operations
        """
        # Initialize components
        self._query_engine = QueryEngine(tech_threshold=0.3)
        self._scraper = DeepScraper(max_concurrent=max_concurrent_scrapes)
        self._url_analyzer = URLAnalyzer()
        self._quality_filter = SourceQualityFilter(strict_mode=True)
        
        # Initialize source queue with premium sources
        self._source_queue = SourcePriorityQueue()
        self._initialize_sources()
        
        # Cap concurrent per-URL analysis in search()'s API-discovery phase
        # at the same budget used for source scraping, so it stays a single,
        # coherent concurrency setting rather than two independent ones.
        self._max_concurrent_analyze = max_concurrent_scrapes
        
        # Initialize dynamic discovery agent (uses APIs if available)
        # Storage will be initialized lazily if crawler articles are discovered
        self._db = None
        self._discovery_agent = WebDiscoveryAgent(self._db)
        
        # URL deduplication
        self._url_dedup = URLDeduplicator(expected_urls=100_000)
        
        # Article storage (in-memory)
        self._articles: List[Article] = []
        
        # Statistics
        self._stats = {
            "queries_processed": 0,
            "queries_rejected": 0,
            "urls_analyzed": 0,
            "articles_scraped": 0,
            "sources_scraped": 0,
            "scrapes_successful": 0,
            "scrapes_failed": 0,
        }
        
        # Cache for response caching (if enabled)
        self._cache: Optional[HTTPResponseCache] = None
        if enable_cache:
            self._cache = HTTPResponseCache(max_responses=1000, default_ttl=300)
        
        # Real-time news feeder (background continuous fetch)
        # Use EnhancedRealtimeFeeder if available (includes discovery aggregator and dedup)
        if ENHANCED_FEEDER_AVAILABLE:
            self._realtime_feeder = EnhancedRealtimeFeeder(
                refresh_interval=30,  # 30 seconds for real-time updates
                max_articles=1000,
                max_age_hours=24,
                enable_discovery=True,  # Enable Google/Bing/NewsAPI
                enable_redis=False,     # Disable Redis for now (optional)
            )
            logger.info("Using EnhancedRealtimeFeeder with discovery aggregator")
        else:
            self._realtime_feeder = RealtimeNewsFeeder(
                refresh_interval=30,  # 30 seconds for real-time updates
                max_articles=500,
                max_age_hours=24
            )
            logger.info("Using standard RealtimeNewsFeeder")
        self._new_article_callback: Optional[Callable[[Article], None]] = None
        
        logger.info("TechNewsOrchestrator initialized")
        
        # Emit initial stats
        self._emit_stats()
        event_bus.publish(LogMessage(
            message="Orchestrator initialized and ready [Events Enabled]",
            level="INFO",
            component="Orchestrator"
        ))

    # Cap on in-memory article history. Without this, self._articles grows
    # without bound for the lifetime of the process -- and this orchestrator
    # is meant to run continuously (start_realtime_feed, search(), etc. all
    # feed into it), so "the lifetime of the process" can be days.
    MAX_STORED_ARTICLES = 2000

    def _store_article(self, article: Article) -> None:
        """Append an article to in-memory storage, trimming the oldest
        entries once MAX_STORED_ARTICLES is exceeded. Centralized here so
        every code path that adds an article shares the same bound instead
        of each maintaining its own copy of this logic."""
        self._articles.append(article)
        overflow = len(self._articles) - self.MAX_STORED_ARTICLES
        if overflow > 0:
            del self._articles[:overflow]

    def _dedupe_and_track(self, url: str) -> bool:
        """Returns True if url is new (and marks it seen); False if duplicate."""
        if self._url_dedup.is_duplicate(url):
            return False
        self._url_dedup.add(url)
        return True

    def _emit_stats(self) -> None:
        """Emit current statistics to the event bus."""
        # Calculate success rate
        total_scrapes = self._stats.get("scrapes_successful", 0) + self._stats.get("scrapes_failed", 0)
        success_rate = 0.0
        if total_scrapes > 0:
            success_rate = self._stats.get("scrapes_successful", 0) / total_scrapes
        
        # Get cache hits
        cache_hits = 0
        if self._cache:
            # HTTPResponseCache wraps LRUCache, access hits through stats property
            cache_hits = self._cache.stats.get('hits', 0)
        elif hasattr(self._scraper, '_cache'):
            # DeepScraper also uses HTTPResponseCache
            if hasattr(self._scraper._cache, 'stats'):
                cache_hits = self._scraper._cache.stats.get('hits', 0)
            elif hasattr(self._scraper._cache, '_hits'):
                # Fallback for direct LRUCache access
                cache_hits = self._scraper._cache._hits
        
        event = StatsUpdate(
            total_articles=len(self._articles),
            total_sources=len(self._source_queue),
            total_requests=self._stats.get("sources_scraped", 0) + self._stats.get("urls_analyzed", 0),
            success_rate=success_rate,
            cache_hits=cache_hits
        )
        event_bus.publish(event)
    
    def _initialize_sources(self) -> None:
        """Initialize source queue with known sources."""
        all_sources = PREMIUM_SOURCES + QUALITY_SOURCES
        
        for source_data in all_sources:
            source = {
                "url": source_data["url"],
                "name": source_data["name"],
                "tier": source_data["tier"].value,
                "success_rate": 1.0,
                "article_rate": 0.5,
                "last_scraped": 0,
            }
            self._source_queue.add_source(source)
        
        logger.info(f"Initialized {len(all_sources)} sources")
    
    async def search(
        self,
        query: str,
        max_articles: int = 20,
        max_sources: int = 5,
    ) -> SearchResult:
        """
        Search for tech news matching the query.
        
        Analyzes the query, validates tech relevance, and scrapes
        multiple sources for matching articles.
        
        Args:
            query: User search query
            max_articles: Maximum articles to return
            max_sources: Maximum sources to scrape
        
        Returns:
            SearchResult with found articles
        
        Raises:
            NonTechQueryError: If query is not tech-related
            InvalidQueryError: If query is malformed
        """
        logger.info(f"Searching: {query}")
        event_bus.publish(LogMessage(message=f"Searching for: {query}", component="Orchestrator"))
        self._emit_stats()
        
        start_time = time.time()
        errors: List[str] = []
        
        # Analyze query
        try:
            query_result = self._query_engine.analyze_strict(query)
        except NonTechQueryError as e:
            self._stats["queries_rejected"] += 1
            raise
        except InvalidQueryError as e:
            self._stats["queries_rejected"] += 1
            raise
        
        self._stats["queries_processed"] += 1
        
        # Handle different intents
        if query_result.intent == QueryIntent.ANALYZE_URL:
            # Extract URL and analyze
            import re
            urls = re.findall(r'https?://[^\s]+', query)
            if urls:
                analysis = await self.analyze_url(urls[0])
                if analysis:
                    return SearchResult(
                        query=query,
                        query_result=query_result,
                        articles=[analysis.article],
                        total_sources_scraped=1,
                        total_time_ms=(time.time() - start_time) * 1000,
                    )
        
        # Get search terms for filtering
        search_terms = self._query_engine.get_search_terms(query_result)
        
        # ═══════════════════════════════════════════════════════════════
        # PHASE 1: API-BASED DISCOVERY (Priority)
        # ═══════════════════════════════════════════════════════════════
        articles: List[Article] = []
        sources_scraped = 0
        
        # Try API-based article discovery first
        if self._discovery_agent.api_available.get("google") or self._discovery_agent.api_available.get("bing"):
            event_bus.publish(LogMessage(
                message="🚀 Using API-based discovery (Google/Bing)",
                component="Orchestrator"
            ))
            
            # Get article URLs directly from search API
            discovered_urls = self._discovery_agent.search_web_for_articles(query, max_results=max_articles)

            # De-dupe within this batch (discovered_urls can itself contain
            # repeats) as well as against anything already seen.
            seen_in_batch: Set[str] = set()
            urls_to_analyze: List[str] = []
            for url in discovered_urls:
                if url in seen_in_batch or not self._dedupe_and_track(url):
                    continue
                seen_in_batch.add(url)
                urls_to_analyze.append(url)

            # Analyze discovered URLs concurrently (bounded). This used to be
            # a sequential `await self.analyze_url(url)` inside this loop --
            # one full fetch-and-analyze round trip at a time -- which is why
            # a ~20-URL search could take 40-60+ seconds. analyze_url()
            # already handles dedup + storing into self._articles, so this
            # loop only needs to collect the results, not re-do that.
            analyze_semaphore = asyncio.Semaphore(self._max_concurrent_analyze)

            async def _analyze_one(url: str) -> Optional[Article]:
                async with analyze_semaphore:
                    try:
                        analysis = await self.analyze_url(url)
                        return analysis.article if analysis and analysis.article else None
                    except Exception as e:
                        errors.append(f"URL analysis failed: {e}")
                        return None

            analyzed_articles = await asyncio.gather(
                *(_analyze_one(url) for url in urls_to_analyze)
            )
            for article in analyzed_articles:
                if article is not None:
                    articles.append(article)
                    self._stats["articles_scraped"] += 1
                    sources_scraped += 1
                    
            event_bus.publish(LogMessage(
                message=f"API Discovery found {len(articles)} articles",
                component="Orchestrator"
            ))
        
        # ═══════════════════════════════════════════════════════════════
        # PHASE 2: STATIC SOURCE SCRAPING (Fallback/Supplement)
        # ═══════════════════════════════════════════════════════════════
        if len(articles) < max_articles:
            event_bus.publish(LogMessage(
                message="📰 Supplementing with static source scraping",
                component="Orchestrator"
            ))
        
        # Get top sources
        sources = self._source_queue.get_all_sources_ordered()[:max_sources]
        
        # Scrape concurrently
        tasks = [
            self._scrape_source_with_filter(source, search_terms)
            for source in sources
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, ScrapingResult):
                sources_scraped += 1
                self._stats["sources_scraped"] += 1
                
                for article in result.articles:
                    if self._dedupe_and_track(article.url):
                        articles.append(article)
                        self._store_article(article)
                        self._stats["articles_scraped"] += 1
            
            elif isinstance(result, Exception):
                errors.append(str(result))
        
        # Sort by tech score and limit
        articles.sort(
            key=lambda a: a.tech_score.score if a.tech_score else 0,
            reverse=True
        )
        
        # Apply quality filtering
        articles = self._quality_filter.filter_articles(articles)
        
        articles = articles[:max_articles]
        
        total_time = (time.time() - start_time) * 1000
        
        logger.info(
            f"Search complete: {len(articles)} articles from "
            f"{sources_scraped} sources in {total_time:.0f}ms"
        )
        
        event_bus.publish(LogMessage(
            message=f"Search finished: {len(articles)} articles found in {total_time:.0f}ms",
            component="Orchestrator"
        ))
        self._emit_stats()
        
        return SearchResult(
            query=query,
            query_result=query_result,
            articles=articles,
            total_sources_scraped=sources_scraped,
            total_time_ms=total_time,
            errors=errors,
        )
    
    async def search_from_sources_only(
        self,
        max_articles: int = 25,
        max_sources: int = 10,
    ) -> List[Article]:
        """
        Fetch news from static sources only (no API discovery).
        
        This method bypasses Dynamic Discovery and only scrapes
        the pre-configured static sources.
        
        Args:
            max_articles: Maximum articles to return
            max_sources: Maximum sources to scrape
        
        Returns:
            List of articles from static sources
        """
        logger.info("Fetching from static sources only...")
        event_bus.publish(LogMessage(
            message="📰 Fetching from static sources only (no API)",
            component="Orchestrator"
        ))
        
        start_time = time.time()
        articles: List[Article] = []
        errors: List[str] = []
        
        # Get sources from queue (no API discovery)
        sources = self._source_queue.get_all_sources_ordered()[:max_sources]
        
        # Load custom sources if any
        custom_sources = self._load_custom_sources()
        for cs in custom_sources[:5]:  # Max 5 custom sources
            sources.append({"url": cs.get("url", cs), "name": cs.get("name", "Custom"), "tier": 3})
        
        # Scrape concurrently
        tasks = [
            self._scraper.scrape_source(source["url"])
            for source in sources
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, ScrapingResult):
                for article in result.articles:
                    if self._dedupe_and_track(article.url):
                        articles.append(article)
                        self._store_article(article)
                        self._stats["articles_scraped"] += 1
            elif isinstance(result, Exception):
                errors.append(str(result))
        
        # Apply quality filtering
        articles = self._quality_filter.filter_articles(articles)
        articles = articles[:max_articles]
        
        total_time = (time.time() - start_time) * 1000
        
        event_bus.publish(LogMessage(
            message=f"Static source fetch complete: {len(articles)} articles in {total_time:.0f}ms",
            component="Orchestrator"
        ))
        self._emit_stats()
        
        return articles
    
    def _load_custom_sources(self) -> List[dict]:
        """Load custom sources from file using the manager."""
        from src.sources.custom_source_loader import CustomSourceManager
        try:
            urls = CustomSourceManager.load_sources()
            return [{"url": url, "name": "Custom"} for url in urls]
        except Exception as exc:
            logger.warning(f"Failed to load custom sources: {exc}")
            return []
    
    async def _scrape_source_with_filter(
        self,
        source: Dict[str, Any],
        search_terms: List[str],
    ) -> ScrapingResult:
        """Scrape a source and filter by search terms."""
        result = await self._scraper.scrape_source(source["url"])
        
        if not search_terms:
            return result
        
        # Filter articles by search terms
        terms_lower = [t.lower() for t in search_terms]
        filtered_articles = []
        
        for article in result.articles:
            content_lower = (article.title + " " + article.content).lower()
            if any(term in content_lower for term in terms_lower):
                filtered_articles.append(article)
        
        return ScrapingResult(
            status=result.status,
            articles=tuple(filtered_articles),
            source=result.source,
            duration_ms=result.duration_ms,
            error_message=result.error_message,
        )
    
    async def analyze_url(self, url: str) -> Optional[URLAnalysisResult]:
        """
        Perform deep analysis of a specific URL.
        
        Args:
            url: URL to analyze
        
        Returns:
            URLAnalysisResult with comprehensive analysis
        """
        logger.info(f"Analyzing URL: {url}")
        self._stats["urls_analyzed"] += 1
        
        result = await self._url_analyzer.analyze(url)
        
        if result:
            # Add to articles if valid
            if self._dedupe_and_track(url):
                self._store_article(result.article)
        
        return result
    
    def analyze_url_with_content(self, url: str, html: str) -> Optional[URLAnalysisResult]:
        """
        Analyze a URL using pre-fetched HTML content.
        
        This method is used when content has already been fetched
        via bypass mechanisms (anti-bot, paywall bypass, etc.).
        
        Args:
            url: Original URL
            html: Pre-fetched HTML content
        
        Returns:
            URLAnalysisResult with comprehensive analysis
        """
        logger.info(f"Analyzing pre-fetched content for: {url}")
        logger.info(f"Content length being passed: {len(html)} chars")
        self._stats["urls_analyzed"] += 1
        
        # URLAnalyzer handles this correctly by delegating to DeepScraper
        # (which now has robust ContentExtractor fixes)
        result = self._url_analyzer.analyze_from_content(url, html)
        
        if result:
            # Add to articles if valid
            if self._dedupe_and_track(url):
                self._store_article(result.article)
                logger.info(f"Successfully analyzed content: {len(result.article.content)} chars")
        else:
            logger.error(f"Failed to analyze pre-fetched content for: {url}")
        
        return result
    
    def format_url_analysis(self, result: URLAnalysisResult) -> str:
        """Format URL analysis as readable report."""
        return self._url_analyzer.format_analysis_report(result)
    
    def validate_query(self, query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a query without executing search.
        
        Args:
            query: Query to validate
        
        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        try:
            result = self._query_engine.analyze(query)
            if result.is_accepted:
                return True, None
            else:
                return False, result.rejection_reason
        except Exception as e:
            return False, str(e)
    
    def suggest_queries(self, failed_query: str) -> List[str]:
        """Get suggested tech queries for a rejected query."""
        return self._query_engine.suggest_tech_queries(failed_query)
    
    def get_latest_articles(self, count: int = 10) -> List[Article]:
        """Get the latest scraped articles."""
        return sorted(
            self._articles,
            key=lambda a: a.scraped_at,
            reverse=True
        )[:count]
    
    def get_top_articles(self, count: int = 10) -> List[Article]:
        """Get top articles by tech score."""
        return sorted(
            self._articles,
            key=lambda a: a.tech_score.score if a.tech_score else 0,
            reverse=True
        )[:count]
    
    def search_articles(self, query: str) -> List[Article]:
        """Search through scraped articles (local search)."""
        query_lower = query.lower()
        matches = []
        
        for article in self._articles:
            content = (article.title + " " + article.content).lower()
            if query_lower in content:
                matches.append(article)
        
        return matches
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return {
            **self._stats,
            "total_articles": len(self._articles),
            "total_sources": len(self._source_queue),
            "scraper_stats": self._scraper.stats,
        }
    
    @property
    def source_count(self) -> int:
        """Get number of configured sources."""
        return len(self._source_queue)
    
    @property
    def article_count(self) -> int:
        """Get number of scraped articles."""
        return len(self._articles)
    
    async def get_realtime_news(
        self,
        count: int = 20,
        max_age_hours: int = 24
    ) -> List[Article]:
        """
        Get real-time news sorted by publication timestamp.
        
        Triggers a refresh on this orchestrator's own real-time feeder and
        returns its latest articles, rather than constructing a separate
        RealtimeNewsFeeder (with its own aiohttp session) on every call --
        that was wasteful (a full fetch cycle against 8 sources per call)
        and never explicitly closed the throwaway feeder's session.

        max_age_hours is honored via whatever self._realtime_feeder was
        already configured with in __init__ (no caller in this codebase
        currently passes a non-default value here).
        
        Args:
            count: Maximum articles to return
            max_age_hours: Maximum article age in hours (see note above)
        
        Returns:
            List of articles sorted by timestamp (newest first)
        """
        await self._realtime_feeder.refresh()
        articles = self._realtime_feeder.get_latest(count)
        
        # Add to internal storage
        for article in articles:
            if self._dedupe_and_track(article.url):
                self._store_article(article)
        
        return articles
    
    def get_articles_sorted_by_time(self, count: int = 20) -> List[Article]:
        """
        Get stored articles sorted by publication timestamp.
        
        Articles without published_at use scraped_at as fallback.
        
        Args:
            count: Maximum articles to return
        
        Returns:
            List of articles sorted by timestamp (newest first)
        """
        from datetime import datetime, UTC
        
        def get_timestamp(article: Article) -> datetime:
            """Get article timestamp with fallback."""
            if article.published_at:
                ts = article.published_at
            else:
                ts = article.scraped_at
            
            # Ensure timezone awareness
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            
            return ts or datetime.min.replace(tzinfo=UTC)
        
        sorted_articles = sorted(
            self._articles,
            key=get_timestamp,
            reverse=True  # Newest first
        )
        
        return sorted_articles[:count]

    # =========================================================================
    # REAL-TIME FEED METHODS
    # =========================================================================
    
    async def start_realtime_feed(self) -> None:
        """
        Start the background continuous news fetching feed.
        
        This starts a background task that periodically fetches news
        from all configured sources and adds them to the article queue.
        """
        # Register internal callback to add to our article storage
        def on_new_article(article: Article):
            if self._dedupe_and_track(article.url):
                self._store_article(article)
                self._stats["articles_scraped"] += 1
                
                # Forward to external callback (GUI)
                if self._new_article_callback:
                    self._new_article_callback(article)
                
                logger.info(f"New article: {article.title[:50]}...")
        
        self._realtime_feeder._new_article_callbacks.append(on_new_article)
        await self._realtime_feeder.start()
        logger.info("Real-time news feed started")
    
    async def stop_realtime_feed(self) -> None:
        """Stop the background continuous news fetching feed."""
        await self._realtime_feeder.stop()
        logger.info("Real-time news feed stopped")
    
    def register_new_article_callback(self, callback: Callable[[Article], None]) -> None:
        """
        Register a callback to be called when new articles are fetched.
        
        Args:
            callback: Function that takes an Article and processes it
        """
        self._new_article_callback = callback
        
        # Also register with the realtime feeder if available
        if self._realtime_feeder:
            # If it's the enhanced feeder, use add_article_callback
            if hasattr(self._realtime_feeder, 'add_article_callback'):
                self._realtime_feeder.add_article_callback(callback)
            # If it's the base feeder, use add_callback
            elif hasattr(self._realtime_feeder, 'add_callback'):
                self._realtime_feeder.add_callback(callback)
    
    def get_realtime_articles(self, count: int = 20) -> List[Article]:
        """
        Get articles from the realtime feeder's priority queue.
        
        Returns articles sorted by timestamp (newest first).
        """
        return self._realtime_feeder.get_latest(count)
    
    async def crawl_website(
        self,
        url: str,
        max_depth: int = 2,
        max_pages: int = 20,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[Article]:
        """
        Crawl a website starting from a seed URL.
        
        Uses EnhancedWebCrawler to discover and process articles,
        adding them to the database and internal storage.
        
        Args:
            url: Seed URL to start crawling from
            max_depth: Maximum crawl depth (1-3)
            max_pages: Maximum pages to crawl
            progress_callback: Optional callback(current, total) for progress updates
        
        Returns:
            List of Article objects found during crawl
        """
        logger.info(f"🕷️ Starting crawl from {url} (depth={max_depth}, pages={max_pages})")
        event_bus.publish(LogMessage(
            message=f"🕷️ Crawling {url} (depth={max_depth}, max_pages={max_pages})",
            component="Orchestrator"
        ))
        
        # Configure crawler
        config = EnhancedCrawlConfig(
            max_depth=max_depth,
            max_pages=max_pages,
            article_only=True,
            stay_on_domain=True,
            extract_content=True,
            parse_sitemaps=True,
            deduplicate_content=True,
            concurrent_requests=3,
            delay_between_requests=0.5,
        )
        
        crawler = EnhancedWebCrawler(config)
        
        # Track discovered articles
        discovered_articles: List[Article] = []
        
        def on_crawl_result(result):
            """Callback for each crawled page."""
            if result.success and result.content:
                # Analyze the crawled content and convert to Article
                try:
                    analysis = self._url_analyzer.analyze_from_content(result.url, result.html)
                    if analysis and analysis.article:
                        # Add to discovered articles if not duplicate
                        if self._dedupe_and_track(result.url):
                            self._store_article(analysis.article)
                            discovered_articles.append(analysis.article)
                            self._stats["articles_scraped"] += 1
                            
                            logger.info(f"  ✓ Found article: {analysis.article.title[:50]}...")
                except Exception as e:
                    logger.warning(f"Failed to analyze crawled page {result.url}: {e}")
        
        try:
            # Run crawl
            await crawler.crawl(
                seed_urls=[url],
                callback=on_crawl_result,
                progress_callback=progress_callback
            )
            
            # Save discovered articles to the database asynchronously
            if discovered_articles:
                try:
                    if self._db is None:
                        from src.storage.sqlite_engine import SqliteEngine
                        from src.storage.sqlite_article_repository import SqliteArticleRepository
                        engine = SqliteEngine()
                        self._db = SqliteArticleRepository(engine=engine)
                except Exception as e:
                    logger.debug(f"Article storage init failed: {e}")
            
            # Get stats
            stats = crawler.get_stats()
            logger.info(f"🕷️ Crawl complete: {len(discovered_articles)} articles from {stats['pages_visited']} pages")
            event_bus.publish(LogMessage(
                message=f"🕷️ Crawl complete: {len(discovered_articles)} articles from {stats['successful_crawls']} pages",
                component="Orchestrator"
            ))
            
            self._emit_stats()
            return discovered_articles
            
        except Exception as e:
            logger.error(f"Crawl failed: {e}")
            event_bus.publish(LogMessage(
                message=f"❌ Crawl failed: {str(e)[:50]}",
                component="Orchestrator",
                level="ERROR"
            ))
            raise
    
    async def shutdown(self) -> None:
        """
        Gracefully shutdown all orchestrator resources.
        
        This should be called before application exit to:
        - Stop the real-time feed
        - Close any open HTTP sessions
        - Cleanup database connections
        """
        logger.info("Orchestrator shutting down...")
        
        # Stop real-time feed
        try:
            await self._realtime_feeder.stop()
        except Exception as e:
            logger.warning(f"Error stopping realtime feeder: {e}")
        
        # Close scraper sessions
        try:
            await self._scraper.close()
        except Exception as e:
            logger.warning(f"Error closing scraper: {e}")
        
        # Close URL analyzer sessions
        try:
            if hasattr(self, '_url_analyzer') and self._url_analyzer:
                await self._url_analyzer.close()
        except Exception as e:
            logger.warning(f"Error closing URL analyzer: {e}")
        
        logger.info("Orchestrator shutdown complete")
