"""
Newsletter Scheduler for Automated Generation

Enables scheduled daily newsletter generation.
"""

import asyncio
import logging
from datetime import datetime, time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class NewsletterScheduler:
    """
    Scheduler for automated newsletter generation.
    
    Uses APScheduler for cron-like scheduling.
    """
    
    def __init__(self):
        """Initialize scheduler."""
        self._scheduler = None
        self._job_id = "newsletter_generation"
        self._on_generate: Optional[Callable] = None
        self._running = False
    
    def _get_scheduler(self):
        """Lazy load APScheduler."""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                from apscheduler.triggers.cron import CronTrigger
                self._scheduler = AsyncIOScheduler()
            except ImportError:
                logger.warning("APScheduler not installed. Run: pip install APScheduler")
                return None
        return self._scheduler
    
    def schedule_daily(
        self,
        hour: int = 6,
        minute: int = 0,
        on_generate: Optional[Callable] = None
    ) -> bool:
        """
        Schedule daily newsletter generation.
        
        Args:
            hour: Hour to generate (0-23)
            minute: Minute to generate (0-59)
            on_generate: Callback function to run for generation
            
        Returns:
            True if scheduled successfully
        """
        scheduler = self._get_scheduler()
        if scheduler is None:
            return False
        
        self._on_generate = on_generate
        
        try:
            from apscheduler.triggers.cron import CronTrigger
            
            # Remove existing job if any
            if scheduler.get_job(self._job_id):
                scheduler.remove_job(self._job_id)
            
            # Add new job
            scheduler.add_job(
                self._run_generation,
                CronTrigger(hour=hour, minute=minute),
                id=self._job_id,
                name="Daily Newsletter Generation"
            )
            
            logger.info(f"Scheduled daily newsletter at {hour:02d}:{minute:02d}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to schedule newsletter: {e}")
            return False
    
    async def _run_generation(self):
        """Internal method to run newsletter generation."""
        logger.info(f"Running scheduled newsletter generation at {datetime.now()}")
        
        if self._on_generate:
            try:
                if asyncio.iscoroutinefunction(self._on_generate):
                    await self._on_generate()
                else:
                    self._on_generate()
            except Exception as e:
                logger.error(f"Scheduled generation failed: {e}")
        else:
            # Default: use newsletter workflow
            try:
                from src.newsletter import generate_newsletter
                result = await generate_newsletter(skip_review=True)
                if result and result.get("final_markdown"):
                    logger.info(f"Newsletter generated: {result.get('export_path')}")
            except Exception as e:
                logger.error(f"Default generation failed: {e}")
    
    def start(self) -> bool:
        """Start the scheduler."""
        scheduler = self._get_scheduler()
        if scheduler is None:
            return False
        
        if not self._running:
            scheduler.start()
            self._running = True
            logger.info("Newsletter scheduler started")
        return True
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler and self._running:
            self._scheduler.shutdown()
            self._running = False
            logger.info("Newsletter scheduler stopped")
    
    def cancel_schedule(self) -> bool:
        """Cancel the scheduled job."""
        scheduler = self._get_scheduler()
        if scheduler and scheduler.get_job(self._job_id):
            scheduler.remove_job(self._job_id)
            logger.info("Newsletter schedule cancelled")
            return True
        return False
    
    def get_next_run(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        scheduler = self._get_scheduler()
        if scheduler:
            job = scheduler.get_job(self._job_id)
            if job:
                return job.next_run_time
        return None
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
    
    @property
    def is_scheduled(self) -> bool:
        """Check if a job is scheduled."""
        scheduler = self._get_scheduler()
        if scheduler:
            return scheduler.get_job(self._job_id) is not None
        return False


# Singleton instance
_scheduler: Optional[NewsletterScheduler] = None


def get_scheduler() -> NewsletterScheduler:
    """Get or create scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = NewsletterScheduler()
    return _scheduler
