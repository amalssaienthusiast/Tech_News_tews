"""
Enhanced Real-Time News Feeder with Multi-Source Discovery.

Integrates:
- DiscoveryAggregator (Google, Bing, NewsAPI)
- DeduplicationEngine (URL, title, content)
- Redis Event Bus for pub/sub (optional)
- Faster 30-second refresh cycles

Usage:
    feeder = EnhancedRealtimeFeeder()
    await feeder.start()
    
    async for article in feeder.stream():
        print(article.title)
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, UTC
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

import aiohttp

# Import original feeder components
from src.engine.realtime_feeder import (
    RealtimeNewsFeeder,
    RobustDateParser,
    Article,
)
from src.core.types import SourceTier
from src.data_structures import BloomFilter
from src.utils.http import create_connector

# Import new discovery and processing modules
from src.sources.aggregator import DiscoveryAggregator, UnifiedArticle
from src.processing.deduplication import DeduplicationEngine
from src.engine.primp_crawler import PrimpRealtimeCrawler
from src.engine.quality_filter import SourceQualityFilter
from src.engine.unified_chain import unified_engine

# Import event bus (optional)
try:
    from src.infrastructure.redis_event_bus import RedisEventBus, LocalEventBus, Event, EventType
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

try:
    from config.settings import (
        REALTIME_REFRESH_INTERVAL,
        DEDUP_TITLE_SIMILARITY_THRESHOLD,
    )
except ImportError:
    REALTIME_REFRESH_INTERVAL = 300
    DEDUP_TITLE_SIMILARITY_THRESHOLD = 0.85



# =============================================================================
# ENHANCED FEEDER
# =============================================================================

class EnhancedRealtimeFeeder(RealtimeNewsFeeder):
    """
    Enhanced real-time news feeder with multi-source discovery.
    
    Improvements over base RealtimeNewsFeeder:
    - Integrates Google News, Bing News, NewsAPI
    - Uses multi-method deduplication
    - 30-second refresh cycles (vs 300 default)
    - Event-driven architecture with Redis pub/sub
    - Status callbacks for GUI integration
    """
    
    def __init__(
        self,
        refresh_interval: int = REALTIME_REFRESH_INTERVAL,
        max_articles: int = 1000,
        max_age_hours: int = 24,
        sources: Optional[List[str]] = None,
        enable_discovery: bool = True,
        enable_redis: bool = True,
    ):
        """
        Initialize enhanced feeder.
        
        Args:
            refresh_interval: Seconds between refreshes (default 30)
            max_articles: Max articles in memory
            max_age_hours: Max article age
            sources: RSS source URLs
            enable_discovery: Enable API-based discovery
            enable_redis: Enable Redis event publishing
        """
        # Initialize base feeder
        super().__init__(
            refresh_interval=refresh_interval,
            max_articles=max_articles,
            max_age_hours=max_age_hours,
            sources=sources,
        )
        
        # Enhanced components
        self._enable_discovery = enable_discovery
        self._enable_redis = enable_redis
        
        # Discovery aggregator (Google, Bing, NewsAPI)
        self._aggregator: Optional[DiscoveryAggregator] = None
        
        # Enhanced deduplication
        self._dedup_engine = DeduplicationEngine(
            title_threshold=DEDUP_TITLE_SIMILARITY_THRESHOLD,
            use_content_hash=True,
        )
        
        # Event bus for pub/sub
        self._event_bus = None
        
        # Status callbacks for GUI
        self._status_callbacks: List[Callable[[str, str], None]] = []
        
        # Refresh cooldown — disabled (0) when used inside EnhancedNewsPipeline,
        # because the pipeline has its own cooldown. This fixes the double-cooldown bug.
        self._refresh_cooldown = 0
        
        # Enhanced stats
        self._enhanced_stats = {
            "google_articles": 0,
            "bing_articles": 0,
            "newsapi_articles": 0,
            "rss_articles": 0,
            "dedup_url": 0,
            "dedup_title": 0,
            "dedup_content": 0,
            "last_refresh_ms": 0,
        }
    

    async def start(self, fresh_start: bool = True, enable_background_refresh: bool = True):
        """
        Start the enhanced feeder.
        
        Args:
            fresh_start: If True, clears old articles before initial fetch
            enable_background_refresh: If False, doesn't start background refresh task
                                      (useful when used by pipeline that controls refreshes)
        """
        logger.info("EnhancedRealtimeFeeder starting...")
        
        # Initialize aggregator
        if self._enable_discovery:
            self._aggregator = DiscoveryAggregator()
            sources = self._aggregator.get_available_sources()
            logger.info(f"Discovery sources available: {sources}")
            self._emit_status("discovery", f"APIs: {', '.join(sources)}")
        
        # Initialize event bus
        if self._enable_redis and EVENT_BUS_AVAILABLE:
            try:
                self._event_bus = RedisEventBus()
                await self._event_bus.connect()
                logger.info("Redis event bus connected")
                self._emit_status("redis", "Connected")
            except Exception as e:
                logger.warning(f"Redis unavailable, using local: {e}")
                self._event_bus = LocalEventBus()
                self._emit_status("redis", "Fallback to local")
        
        # Start unified engine continuous scheduler
        self._running = True
        await unified_engine.start()

        # Ensure session exists
        if self._session is None or self._session.closed:
             self._session = aiohttp.ClientSession(
                headers={"User-Agent": self.USER_AGENT},
                connector=create_connector()
            )

        logger.info("EnhancedRealtimeFeeder started via Unified Feed Chain")
        self._emit_status("feeder", "Active")
    
    async def stop(self) -> None:
        """Stop feeder and background scheduler workers."""
        self._running = False
        unified_engine.stop()
        await super().stop()
        logger.info("EnhancedRealtimeFeeder stopped")
    
    async def refresh(self) -> int:
        """
        Delegates refresh to Unified Feed Chain Engine.
        """
        await unified_engine.start()
        articles = unified_engine.get_articles(count=100)
        return len(articles)
    
    
    async def _fetch_rss_sources(self) -> int:
        """Fetch from RSS sources with enhanced dedup."""
        new_articles = 0
        
        tasks = [
            self._fetch_source(self._session, source)
            for source in self._sources
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for articles in results:
            if isinstance(articles, list):
                for article in articles:
                    # Use enhanced dedup - use summary or content for dedup
                    article_content = getattr(article, 'summary', '') or getattr(article, 'content', '')
                    dedup_result = self._dedup_engine.check(
                        url=article.url,
                        title=article.title,
                        content=article_content,
                        article_id=article.id,
                    )
                    
                    if dedup_result.is_duplicate:
                        self._stats["duplicates_skipped"] += 1
                        if dedup_result.reason == "url_match":
                            self._enhanced_stats["dedup_url"] += 1
                        elif dedup_result.reason == "title_similar":
                            self._enhanced_stats["dedup_title"] += 1
                        elif dedup_result.reason == "content_similar":
                            self._enhanced_stats["dedup_content"] += 1
                        continue
                    
                    # Add to queue
                    if self._add_article(article):
                        new_articles += 1
                        self._notify_callbacks(article)
        
        return new_articles
    
    def _process_unified_article(self, unified: UnifiedArticle) -> bool:
        """
        Process a unified article from discovery.
        
        Returns:
            True if article was added (not duplicate)
        """
        # Check deduplication
        dedup_result = self._dedup_engine.check(
            url=unified.url,
            title=unified.title,
            content=unified.description or unified.content or "",
            article_id=unified.id,
        )
        
        if dedup_result.is_duplicate:
            self._stats["duplicates_skipped"] += 1
            if dedup_result.reason == "url_match":
                self._enhanced_stats["dedup_url"] += 1
            elif dedup_result.reason == "title_similar":
                self._enhanced_stats["dedup_title"] += 1
            return False
        
        # Track source
        if unified.source_api == "google":
            self._enhanced_stats["google_articles"] += 1
        elif unified.source_api == "bing":
            self._enhanced_stats["bing_articles"] += 1
        elif unified.source_api == "newsapi":
            self._enhanced_stats["newsapi_articles"] += 1
        
        # Convert to Article (realtime_feeder's Article, not core/types)
        # The realtime feeder Article has different fields
        from src.engine.realtime_feeder import Article as FeedArticle
        from src.core.types import SourceTier
        
        article = FeedArticle(
            id=unified.id,
            url=unified.url,
            title=unified.title,
            content=unified.content or unified.description or "",
            summary=unified.description or "",
            source=unified.source or "Unknown",
            source_tier=SourceTier.TIER_2,  # Default to Tier 2 for API sources
            published_at=unified.published_at,
            image_url=unified.image_url,
            category=unified.category,
        )
        
        # Add to queue
        if self._add_article(article):
            self._stats["articles_added"] += 1
            self._notify_callbacks(article)
            return True
        
        return False
    
    def _notify_callbacks(self, article: Article):
        """Notify article callbacks."""
        for callback in self._new_article_callbacks:
            try:
                callback(article)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    async def _publish_refresh_event(self, count: int):
        """Publish refresh event to Redis."""
        if not self._event_bus:
            return
        
        event = Event(
            type=EventType.ARTICLE_NEW,
            data={
                "count": count,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "enhanced_feeder",
            },
        )
        
        await self._event_bus.publish("news:all", event)
    
    def add_article_callback(self, callback: Callable[[Article], None]):
        """Add callback for new articles."""
        if callback not in self._new_article_callbacks:
            self._new_article_callbacks.append(callback)

    def add_status_callback(self, callback: Callable[[str, str], None]):
        """Add callback for status updates (GUI integration)."""
        self._status_callbacks.append(callback)
    
    def _emit_status(self, component: str, status: str):
        """Emit status update to callbacks."""
        for callback in self._status_callbacks:
            try:
                callback(component, status)
            except Exception as e:
                logger.debug(f"Status callback error: {e}")
    
    def get_enhanced_stats(self) -> Dict[str, Any]:
        """Get enhanced statistics."""
        base_stats = self.get_stats()
        return {
            **base_stats,
            **self._enhanced_stats,
            "dedup_stats": self._dedup_engine.get_stats(),
            "discovery_enabled": self._enable_discovery,
            "redis_enabled": self._event_bus is not None,
        }


# =============================================================================
# ENHANCED NEWS PIPELINE (Unified Orchestrator)
# =============================================================================

class EnhancedNewsPipeline:
    """
    Unified News Pipeline - Orchestrates ALL fetching strategies in parallel.
    
    This is the single entry point for triggering news fetching. It:
    - Runs all fetchers simultaneously (RSS, APIs, Web Scraping)
    - Deduplicates results by URL and similar titles
    - Sorts by timestamp (newest first)
    - Provides status callbacks for GUI progress
    - No artificial delays - pure async performance
    
    Usage:
        pipeline = EnhancedNewsPipeline()
        await pipeline.start()
        
        # Single trigger to fetch from ALL sources
        articles = await pipeline.fetch_unified_live_feed()
        
        # Cleanup
        await pipeline.stop()
    """
    
    def __init__(
        self,
        enable_discovery: bool = True,
        max_articles: int = 500,
        max_age_hours: int = 48,
    ):
        """
        Initialize the unified pipeline.
        
        Args:
            enable_discovery: Enable API-based discovery (Google, Bing, etc.)
            max_articles: Maximum articles to return
            max_age_hours: Maximum article age to include
        """
        self._enable_discovery = enable_discovery
        self._max_articles = max_articles
        self._max_age_hours = max_age_hours
        
        # Core components
        self._feeder: Optional[EnhancedRealtimeFeeder] = None
        self._aggregator: Optional[DiscoveryAggregator] = None
        self._dedup_engine = DeduplicationEngine(
            title_threshold=DEDUP_TITLE_SIMILARITY_THRESHOLD,
            use_content_hash=True,
        )
        self._primp_crawler: Optional[PrimpRealtimeCrawler] = None
        self._quality_filter = SourceQualityFilter(
            strict_mode=True, max_age_hours=max_age_hours
        )
        
        # Shared HTTP session
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Status callbacks for GUI
        self._status_callbacks: List[Callable[[str, str], None]] = []
        self._article_callbacks: List[Callable[[Article], None]] = []
        
        # State
        self._running = False
        self._last_fetch: Optional[datetime] = None
        
        # Refresh cooldown settings
        self._refresh_cooldown = 60   # 1 minute between full refreshes
        self._cached_articles: List[Article] = []  # Cached results during cooldown
        
        # Statistics
        self._stats = {
            "total_fetches": 0,
            "total_articles": 0,
            "rss_articles": 0,
            "api_articles": 0,
            "duplicates_filtered": 0,
            "last_fetch_ms": 0,
            "cooldown_skips": 0,
        }

        # Standard pipeline rate limiting
        self._max_publish_per_cycle = 20      # Max articles pushed per fetch cycle
        self._publish_interval_seconds = 120  # 2-minute gap between each article push
    
    async def start(self) -> None:
        """Start the pipeline and initialize components."""
        if self._running:
            return
        
        self._running = True
        self._emit_status("pipeline", "Starting...")
        
        # Initialize feeder (handles RSS sources)
        # Note: We don't start the feeder's background refresh task since we control refreshes via fetch_unified_live_feed()
        self._feeder = EnhancedRealtimeFeeder(
            refresh_interval=300,  # 5 minutes (longer since we control it manually)
            max_articles=self._max_articles,
            max_age_hours=self._max_age_hours,
            enable_discovery=False,  # We handle discovery separately
            enable_redis=False,
        )
        # Don't start the feeder's background refresh - we control it via pipeline
        # The feeder will only refresh when explicitly called, not automatically
        
        # Initialize aggregator (handles APIs)
        if self._enable_discovery:
            self._aggregator = DiscoveryAggregator()
            sources = self._aggregator.get_available_sources()
            logger.info(f"Pipeline: {len(sources)} discovery sources available")
            self._emit_status("discovery", f"Sources: {', '.join(sources)}")
            
        self._primp_crawler = PrimpRealtimeCrawler()
        
        # Create shared session
        self._session = aiohttp.ClientSession(
            headers={"User-Agent": EnhancedRealtimeFeeder.USER_AGENT},
            connector=create_connector(limit=50),
        )
        
        self._emit_status("pipeline", "Ready")
        logger.info("EnhancedNewsPipeline started")
    
    async def stop(self) -> None:
        """Stop the pipeline and cleanup resources."""
        self._running = False
        self._emit_status("pipeline", "Stopping...")
        
        # Close feeder
        if self._feeder:
            await self._feeder.stop()
            self._feeder = None
        
        # Close aggregator
        if self._aggregator:
            await self._aggregator.close()
            self._aggregator = None
        
        # Close session
        if self._session and not self._session.closed:
            await self._session.close()
            await asyncio.sleep(0.25)  # Allow connector to drain
            self._session = None
        
        self._emit_status("pipeline", "Stopped")
        logger.info("EnhancedNewsPipeline stopped")
    
    async def fetch_unified_live_feed(
        self,
        count: int = 1000,
        topics: List[str] = None,
    ) -> List[Article]:
        """
        Fetch from Unified Feed Chain.
        """
        if not self._running:
            await self.start()

        # Ensure background CyclicSourceScheduler is active
        await unified_engine.start()

        # Execute single parallel pass over active fetchers if FeedChain queue is low
        all_articles: List[Article] = unified_engine.get_articles(count=count)
        if len(all_articles) >= count // 2:
            return all_articles[:count]

        # Execute fallback fetch tasks concurrently
        tasks = []
        if self._feeder:
            tasks.append(self._fetch_rss())
        if self._aggregator:
            tasks.append(self._fetch_discovery(topics))
        if self._primp_crawler:
            tasks.append(self._fetch_primp_crawler())

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    for article in r:
                        if not unified_engine.dedup.check_and_add(article):
                            if unified_engine.quality.check(article):
                                await unified_engine.feed.push(article)

        all_articles.extend(unified_engine.get_articles(count=count))

        # Standard pipeline: tag all articles and enforce rate limiting
        tagged: List[Article] = []
        for article in all_articles[:count]:
            if article.pipeline is None:
                article.pipeline = "standard"
            tagged.append(article)

        # Cap to max_publish_per_cycle for standard pipeline delivery
        return tagged[:self._max_publish_per_cycle]
    
    
    async def _fetch_rss(self) -> List[Article]:
        """Fetch from RSS sources."""
        articles = []
        try:
            # Share our session with the feeder
            self._feeder._session = self._session
            
            # Dynamically inject Custom Sources so they are fetched in the live loop
            try:
                from src.sources.custom_source_loader import CustomSourceManager
                custom_sources = CustomSourceManager.load_sources()
                for url in custom_sources:
                    if url not in self._feeder._sources:
                        self._feeder._sources.append(url)
            except Exception as e:
                logger.debug(f"Failed to load custom sources in _fetch_rss: {e}")
            
            # Refresh feeds (feeder's refresh() has its own cooldown)
            # Only refresh if not in cooldown - the feeder will handle this
            await self._feeder.refresh()
            
            # Get latest articles
            rss_articles = self._feeder.get_latest(1000)
            articles.extend(rss_articles)
            
            self._stats["rss_articles"] = len(articles)
            self._emit_status("rss", f"✓ {len(articles)} from RSS")
            
        except Exception as e:
            logger.error(f"RSS fetch error: {e}")
            self._emit_status("rss", f"Error: {str(e)[:30]}")
        
        return articles
    
    async def _fetch_discovery(self, topics: List[str] = None) -> List[Article]:
        """Fetch from discovery APIs (parallel)."""
        articles = []
        try:
            topics = topics or ["technology", "business", "science"]
            
            # Fetch from aggregator
            unified_articles = await self._aggregator.discover_all(
                session=self._session,
                topics=topics,
                queries=[],  # No keyword queries - topic-based RSS
                max_per_source=100,
            )
            
            # Convert UnifiedArticle to Article
            for ua in unified_articles:
                article = Article(
                    id=ua.id,
                    url=ua.url,
                    title=ua.title,
                    content=ua.content or ua.description or "",
                    summary=ua.description or "",
                    source=ua.source,
                    source_tier=SourceTier.TIER_2,
                    published_at=ua.published_at,
                    scraped_at=datetime.now(UTC),
                )
                articles.append(article)
            
            self._stats["api_articles"] = len(articles)
            self._emit_status("api", f"✓ {len(articles)} from APIs")
            
        except Exception as e:
            logger.error(f"Discovery fetch error: {e}")
            self._emit_status("api", f"Error: {str(e)[:30]}")
        
        return articles
    
    async def _fetch_directory_scraper(self) -> List[Article]:
        """Fetch from directory scraper (existing news sites)."""
        articles = []
        try:
            from src.engine.directory_scraper import DirectoryScraper
            import hashlib
            
            self._emit_status("scraper", "Scraping news directories...")
            
            scraper = DirectoryScraper()
            headlines = await scraper.bulk_harvest(
                limit_per_directory=15,
                total_limit=50,
            )
            
            for headline in headlines:
                article_id = hashlib.md5(headline.url.encode()).hexdigest()
                
                # Parse published date
                published_at = None
                if headline.published:
                    try:
                        from src.engine.realtime_feeder import RobustDateParser
                        published_at = RobustDateParser.parse(headline.published, headline.url)
                    except Exception as e:
                        logger.debug(f"_fetch_directory_scraper: suppressed {type(e).__name__}: {e}")
                        pass
                
                article = Article(
                    id=article_id,
                    url=headline.url,
                    title=headline.title,
                    content=headline.summary or "",
                    summary=headline.summary or "",
                    source=headline.source,
                    source_tier=SourceTier.TIER_2,
                    published_at=published_at,
                    scraped_at=datetime.now(UTC),
                )
                articles.append(article)
            
            self._emit_status("scraper", f"✓ {len(articles)} from directories")
            
        except Exception as e:
            logger.error(f"Directory scraper error: {e}")
            self._emit_status("scraper", f"Error: {str(e)[:30]}")
        
        return articles
        
    async def _fetch_primp_crawler(self) -> List[Article]:
        """Fetch real-time news using advanced primp impersonation."""
        self._emit_status("primp", "Running advanced browser engine scraper...")
        try:
            articles = await self._primp_crawler.fetch_realtime_news(limit_per_site=10)
            self._emit_status("primp", f"✓ {len(articles)} headlines scraped via primp")
            return articles
        except Exception as e:
            logger.error(f"Primp crawler error: {e}")
            self._emit_status("primp", f"Error: {str(e)[:30]}")
            return []
    
    def _deduplicate_articles(self, articles: List[Article]) -> List[Article]:
        """Deduplicate articles by URL and title similarity."""
        unique = []
        duplicates = 0
        
        for article in articles:
            result = self._dedup_engine.check(
                url=article.url,
                title=article.title,
                content=article.summary or "",
                article_id=article.id,
            )
            
            if result.is_duplicate:
                duplicates += 1
                continue
            
            unique.append(article)
        
        self._stats["duplicates_filtered"] = duplicates
        logger.debug(f"Deduplication: {len(unique)} unique, {duplicates} duplicates")
        
        return unique
    
    def add_status_callback(self, callback: Callable[[str, str], None]) -> None:
        """Add callback for status updates."""
        self._status_callbacks.append(callback)
    
    def add_article_callback(self, callback: Callable[[Article], None]) -> None:
        """Add callback for new articles."""
        self._article_callbacks.append(callback)
    
    def _emit_status(self, component: str, status: str) -> None:
        """Emit status update to callbacks."""
        for callback in self._status_callbacks:
            try:
                callback(component, status)
            except Exception as e:
                logger.debug(f"Status callback error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return {
            **self._stats,
            "running": self._running,
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "discovery_enabled": self._enable_discovery,
        }
    
    @property
    def last_fetch(self) -> Optional[datetime]:
        """Get last fetch time."""
        return self._last_fetch


# =============================================================================
# STANDALONE RUNNER
# =============================================================================

async def main():
    """Test the enhanced feeder."""
    logging.basicConfig(level=logging.INFO)
    
    feeder = EnhancedRealtimeFeeder(
        refresh_interval=30,
        enable_discovery=True,
        enable_redis=False,
    )
    
    # Status callback for testing
    feeder.add_status_callback(lambda c, s: print(f"[{c}] {s}"))
    
    try:
        await feeder.start()
        
        # Run for 2 minutes
        for i in range(4):
            await asyncio.sleep(30)
            print(f"\n--- Stats after {(i+1)*30}s ---")
            stats = feeder.get_enhanced_stats()
            print(f"Articles: {stats.get('articles_added', 0)}")
            print(f"Google: {stats.get('google_articles', 0)}")
            print(f"Bing: {stats.get('bing_articles', 0)}")
            print(f"NewsAPI: {stats.get('newsapi_articles', 0)}")
            print(f"RSS: {stats.get('rss_articles', 0)}")
            print(f"Dedup: URL={stats.get('dedup_url', 0)} Title={stats.get('dedup_title', 0)}")
    finally:
        await feeder.stop()


if __name__ == "__main__":
    asyncio.run(main())
