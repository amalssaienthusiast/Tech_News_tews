"""
Celery Queue Module for Tech News Scraper.

Provides distributed task processing for:
- Source scraping
- Article analysis
- Feed refresh
- Database maintenance
"""

from src.queue.celery_app import celery_app, get_celery_app
from src.queue.priority_queue import (
    IngestionPriority,
    PrioritizedItem,
    QueueMetrics,
    StarvationSafeIngestionQueue,
)
from src.queue.tasks import (
    analyze_article,
    cleanup_old_articles,
    refresh_feed,
    scrape_source,
)

__all__ = [
    "celery_app",
    "get_celery_app",
    "scrape_source",
    "analyze_article",
    "refresh_feed",
    "cleanup_old_articles",
    "IngestionPriority",
    "PrioritizedItem",
    "QueueMetrics",
    "StarvationSafeIngestionQueue",
]
