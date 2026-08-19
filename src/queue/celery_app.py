"""
Celery Application Factory.

Configures Celery with Redis broker for distributed task processing.
Supports both async and sync tasks with proper serialization.

Usage:
    # Start worker
    celery -A src.queue.celery_app worker --loglevel=info
    
    # Start beat scheduler
    celery -A src.queue.celery_app beat --loglevel=info
"""

import os
import logging
from typing import Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# Check for Celery
try:
    from celery import Celery
    from celery.schedules import crontab
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    logger.warning("Celery not installed. Distributed queue disabled. Install with: pip install celery>=5.3.0")


def create_celery_app(
    broker_url: Optional[str] = None,
    result_backend: Optional[str] = None,
    app_name: str = "tech_news_scraper",
) -> Optional["Celery"]:
    """
    Create and configure Celery application.
    
    Args:
        broker_url: Redis broker URL. Falls back to CELERY_BROKER_URL env var.
        result_backend: Result backend URL. Falls back to CELERY_RESULT_BACKEND env var.
        app_name: Application name for task namespacing.
        
    Returns:
        Configured Celery app or None if Celery unavailable.
    """
    if not CELERY_AVAILABLE:
        logger.error("Cannot create Celery app: celery not installed")
        return None
    
    # Configuration from environment
    broker = broker_url or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    backend = result_backend or os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    
    app = Celery(
        app_name,
        broker=broker,
        backend=backend,
        include=[
            "src.queue.tasks",
        ],
    )
    
    # Celery configuration
    app.conf.update(
        # Serialization
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        
        # Timezone
        timezone="UTC",
        enable_utc=True,
        
        # Task settings
        task_track_started=True,
        task_time_limit=300,  # 5 minutes max per task
        task_soft_time_limit=240,  # Soft limit before hard kill
        
        # Result settings
        result_expires=3600,  # Results expire after 1 hour
        
        # Worker settings
        worker_prefetch_multiplier=4,
        worker_concurrency=4,  # 4 concurrent workers
        
        # Retry settings
        task_default_retry_delay=60,  # 1 minute retry delay
        task_max_retries=3,
        
        # Rate limiting
        task_annotations={
            "src.queue.tasks.scrape_source": {
                "rate_limit": "10/m",  # 10 per minute
            },
            "src.queue.tasks.analyze_article": {
                "rate_limit": "20/m",  # 20 per minute
            },
        },
        
        # Beat schedule for periodic tasks
        beat_schedule={
            "refresh-feed-every-30-seconds": {
                "task": "src.queue.tasks.refresh_feed",
                "schedule": 30.0,  # Every 30 seconds
            },
            "cleanup-old-articles-daily": {
                "task": "src.queue.tasks.cleanup_old_articles",
                "schedule": crontab(hour=3, minute=0),  # 3 AM daily
            },
        },
    )
    
    logger.info(f"Celery app '{app_name}' configured with broker: {broker}")
    return app


@lru_cache(maxsize=1)
def get_celery_app() -> Optional["Celery"]:
    """Get or create the singleton Celery app instance."""
    return create_celery_app()


# Create default app instance
celery_app = get_celery_app() if CELERY_AVAILABLE else None


# Graceful fallback for when Celery is not available
class FallbackTaskRunner:
    """
    Synchronous task runner for when Celery is unavailable.
    Executes tasks directly instead of queuing.
    """
    
    def __init__(self):
        self._tasks = {}
    
    def task(self, *args, **kwargs):
        """Decorator to register tasks."""
        def decorator(func):
            self._tasks[func.__name__] = func
            
            # Add delay method for API compatibility
            def delay(*task_args, **task_kwargs):
                logger.debug(f"Fallback: Executing {func.__name__} synchronously")
                return func(*task_args, **task_kwargs)
            
            func.delay = delay
            func.apply_async = lambda args=None, kwargs=None: func(*(args or []), **(kwargs or {}))
            return func
        
        if args and callable(args[0]):
            return decorator(args[0])
        return decorator
    
    def send_task(self, name, args=None, kwargs=None):
        """Execute task by name."""
        if name in self._tasks:
            return self._tasks[name](*(args or []), **(kwargs or {}))
        raise ValueError(f"Unknown task: {name}")


# Use fallback if Celery not available
fallback_app = FallbackTaskRunner()


def get_task_decorator():
    """Get the appropriate task decorator (Celery or fallback)."""
    if celery_app:
        return celery_app.task
    return fallback_app.task
