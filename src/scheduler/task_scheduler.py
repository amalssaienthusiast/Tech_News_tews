# src/scheduler/task_scheduler.py
"""Native asyncio task scheduler replacing the abandoned aioschedule library."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable, List, Optional

logger = logging.getLogger(__name__)

class ScraperScheduler:
    """Schedules periodic background tasks using native asyncio."""
    
    def __init__(self):
        self._tasks: List[asyncio.Task] = []
        self._running = False

    def every(self, interval_seconds: int, func: Callable[[], Awaitable[None]], *args, **kwargs) -> None:
        """Schedule a coroutine to run every `interval_seconds`."""
        if not self._running:
            return

        async def _run_periodic():
            while self._running:
                try:
                    await func(*args, **kwargs)
                except Exception as exc:
                    logger.error(f"Error in scheduled task {func.__name__}: {exc}")
                await asyncio.sleep(interval_seconds)

        task = asyncio.create_task(_run_periodic())
        self._tasks.append(task)

    def start(self) -> None:
        """Start the scheduler."""
        self._running = True
        logger.info("Asyncio ScraperScheduler started.")

    def stop(self) -> None:
        """Stop the scheduler and cancel all pending tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("Asyncio ScraperScheduler stopped.")
