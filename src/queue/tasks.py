"""
Celery Task Definitions.

Defines distributed tasks for:
- Source scraping (per-source fetching)
- Article analysis (deep content analysis)
- Feed refresh (periodic discovery)
- Database maintenance (cleanup old data)
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, UTC

from src.queue.celery_app import get_task_decorator, CELERY_AVAILABLE

logger = logging.getLogger(__name__)

# Get appropriate decorator (Celery or fallback)
task = get_task_decorator()


def run_async(coro):
    """Helper to run async code in sync context."""
    try:
        asyncio.get_running_loop()
        # Already inside a running loop (e.g. Celery async worker).
        # Offload to a fresh thread so asyncio.run() can create its own loop.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        # No running loop — safe to call asyncio.run() directly.
        return asyncio.run(coro)


# =============================================================================
# SCRAPING TASKS
# =============================================================================

@task(bind=True, max_retries=3, default_retry_delay=60)
def scrape_source(self, source_name: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Scrape articles from a specific source.
    
    Args:
        source_name: Name of source (google, bing, newsapi, duckduckgo, reddit, twitter)
        options: Source-specific options
        
    Returns:
        Dict with status, article count, and timing info
    """
    options = options or {}
    start_time = datetime.utcnow()
    
    try:
        logger.info(f"[Celery] Scraping source: {source_name}")
        
        async def do_scrape():
            import aiohttp
            from src.sources import DiscoveryAggregator
            
            aggregator = DiscoveryAggregator()
            
            async with aiohttp.ClientSession() as session:
                # Fetch from specific source based on name
                if source_name == "google":
                    articles = await aggregator._fetch_google(
                        session, 
                        topics=options.get("topics", ["technology"]),
                        queries=options.get("queries", [])
                    )
                elif source_name == "bing":
                    articles = await aggregator._fetch_bing(
                        session,
                        queries=options.get("queries", ["tech news"])
                    )
                elif source_name == "newsapi":
                    articles = await aggregator._fetch_newsapi(session)
                elif source_name == "duckduckgo":
                    articles = await aggregator._fetch_duckduckgo(
                        session,
                        queries=options.get("queries", ["tech news"])
                    )
                elif source_name == "reddit":
                    articles = await aggregator._fetch_reddit(session)
                elif source_name == "twitter":
                    articles = await aggregator._fetch_twitter()
                else:
                    raise ValueError(f"Unknown source: {source_name}")
                
                return [a.to_dict() for a in articles]
        
        articles = run_async(do_scrape())
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.info(f"[Celery] Scraped {len(articles)} articles from {source_name} in {duration:.2f}s")
        
        return {
            "status": "success",
            "source": source_name,
            "article_count": len(articles),
            "duration_seconds": duration,
            "articles": articles,
        }
        
    except Exception as e:
        logger.error(f"[Celery] Scrape failed for {source_name}: {e}")
        
        # Retry on failure
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {
            "status": "error",
            "source": source_name,
            "error": str(e),
            "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
        }


@task(bind=True, max_retries=2, default_retry_delay=30)
def analyze_article(self, article_url: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Perform deep analysis on a single article.
    
    Args:
        article_url: URL of article to analyze
        options: Analysis options (bypass enabled, etc.)
        
    Returns:
        Analysis results dict
    """
    options = options or {}
    start_time = datetime.utcnow()
    
    try:
        logger.info(f"[Celery] Analyzing article: {article_url[:60]}...")
        
        async def do_analyze():
            from src.engine import TechNewsOrchestrator
            
            orchestrator = TechNewsOrchestrator()
            await orchestrator.initialize()
            
            try:
                result = await orchestrator.analyze_url(article_url)
                if result:
                    return {
                        "title": result.article.title if result.article else None,
                        "key_points": [kp.text for kp in result.key_points] if result.key_points else [],
                        "sentiment": result.sentiment.value if hasattr(result.sentiment, 'value') else str(result.sentiment),
                        "reading_time_min": result.reading_time_min,
                        "entities": {
                            "companies": result.entities.companies if result.entities else [],
                            "technologies": result.entities.technologies if result.entities else [],
                        }
                    }
                return None
            finally:
                await orchestrator.shutdown()
        
        analysis = run_async(do_analyze())
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        if analysis:
            logger.info(f"[Celery] Analysis complete for {article_url[:40]}... ({duration:.2f}s)")
            return {
                "status": "success",
                "url": article_url,
                "analysis": analysis,
                "duration_seconds": duration,
            }
        else:
            return {
                "status": "no_result",
                "url": article_url,
                "duration_seconds": duration,
            }
        
    except Exception as e:
        logger.error(f"[Celery] Analysis failed for {article_url}: {e}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {
            "status": "error",
            "url": article_url,
            "error": str(e),
            "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
        }


# =============================================================================
# PERIODIC TASKS
# =============================================================================

@task
def refresh_feed() -> Dict[str, Any]:
    """
    Periodic task to refresh the news feed from all sources.
    Triggered by Celery Beat every 30 seconds.
    
    Returns:
        Discovery statistics
    """
    start_time = datetime.utcnow()
    
    try:
        logger.info("[Celery] Starting feed refresh...")
        
        async def do_refresh():
            import aiohttp
            from src.sources import DiscoveryAggregator
            
            aggregator = DiscoveryAggregator()
            
            async with aiohttp.ClientSession() as session:
                articles = await aggregator.discover_all(
                    session,
                    topics=["technology", "AI", "startups"],
                    queries=["tech news", "AI news"],
                )
                return aggregator.get_stats(), len(articles)
        
        stats, count = run_async(do_refresh())
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.info(f"[Celery] Feed refresh complete: {count} articles in {duration:.2f}s")
        
        return {
            "status": "success",
            "articles_discovered": count,
            "duration_seconds": duration,
            "stats": stats,
        }
        
    except Exception as e:
        logger.error(f"[Celery] Feed refresh failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
        }


@task
def cleanup_old_articles(days_old: int = 30) -> Dict[str, Any]:
    """
    Cleanup articles older than specified days.
    Triggered by Celery Beat daily at 3 AM.
    
    Args:
        days_old: Delete articles older than this many days
        
    Returns:
        Cleanup statistics
    """
    start_time = datetime.now(UTC)
    cutoff_date = datetime.now(UTC) - timedelta(days=days_old)
    
    try:
        logger.info(f"[Celery] Cleaning up articles older than {days_old} days...")
        
        # Clean up articles from canonical storage
        import os
        from pathlib import Path
        import sqlite3
        from src.storage.sqlite_engine import DEFAULT_CANONICAL_DB_PATH

        db_path_env = os.getenv("TECHNEWS_CANONICAL_DB_PATH") or os.getenv("CANONICAL_DB_PATH")
        db_path = Path(db_path_env) if db_path_env else DEFAULT_CANONICAL_DB_PATH

        deleted_count = 0
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("DELETE FROM canonical_articles WHERE discovered_at < ?", (cutoff_date.isoformat(),))
                    deleted_count += cursor.rowcount
                except Exception as e:
                    logger.debug(f"canonical_articles cleanup error: {e}")
                conn.commit()
        
        logger.info(f"[Celery] Deleted {deleted_count} articles older than {days_old} days")
        
        duration = (datetime.now(UTC) - start_time).total_seconds()
        
        logger.info(f"[Celery] Cleanup complete: {deleted_count} articles removed in {duration:.2f}s")
        
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "duration_seconds": duration,
        }
        
    except Exception as e:
        logger.error(f"[Celery] Cleanup failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
        }


# =============================================================================
# BATCH TASKS
# =============================================================================

@task
def scrape_all_sources() -> Dict[str, Any]:
    """
    Scrape all available sources in parallel.
    Chains individual scrape tasks.
    
    Returns:
        Combined results from all sources
    """
    sources = ["google", "duckduckgo", "reddit"]
    
    # Optionally add API sources if configured
    import os
    if os.getenv("BING_API_KEY"):
        sources.append("bing")
    if os.getenv("NEWSAPI_KEY"):
        sources.append("newsapi")
    if os.getenv("TWITTER_BEARER_TOKEN"):
        sources.append("twitter")
    
    logger.info(f"[Celery] Starting parallel scrape of {len(sources)} sources")
    
    # Queue individual tasks
    results = []
    for source in sources:
        if CELERY_AVAILABLE:
            # Queue as async task
            result = scrape_source.delay(source)
            results.append({"source": source, "task_id": result.id})
        else:
            # Run synchronously
            result = scrape_source(source)
            results.append(result)
    
    return {
        "status": "queued" if CELERY_AVAILABLE else "completed",
        "sources": sources,
        "results": results,
    }
