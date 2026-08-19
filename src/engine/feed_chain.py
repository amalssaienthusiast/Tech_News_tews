"""
FeedChain - Realtime Article Stream Push & Dispatch Engine.

Acts as the live stream target for CyclicSourceScheduler.
Allows immediate push to GUI/WebSocket/API callbacks per article, with drain functionality for batch initial loads.
"""

import asyncio
import logging
from typing import List, Callable, Optional, Any

from ..core.types import Article

logger = logging.getLogger(__name__)

ArticleCallback = Callable[[Article], None]

class FeedChain:
    """
    Central push target and realtime article broker.
    """

    def __init__(self, maxsize: int = 5000):
        self._queue: asyncio.Queue[Article] = asyncio.Queue(maxsize=maxsize)
        self._callbacks: List[ArticleCallback] = []

    def subscribe(self, callback: ArticleCallback) -> None:
        """Register a consumer callback to receive articles instantly upon clearance."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            logger.debug(f"FeedChain callback registered: {callback}")

    def unsubscribe(self, callback: ArticleCallback) -> None:
        """Remove a consumer callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def push(self, article: Article) -> None:
        """
        Push single article into queue and trigger all active subscriber callbacks instantly.
        """
        if not article or not article.title or not article.title.strip():
            return
        if article.title.strip().lower() in ("untitled", "no title", "none", "unknown"):
            return

        try:
            self._queue.put_nowait(article)
        except asyncio.QueueFull:
            # Drop oldest article if queue reaches capacity limit
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(article)
            except Exception:
                pass

        # Trigger registered consumer callbacks
        for cb in list(self._callbacks):
            try:
                cb(article)
            except Exception as e:
                logger.error(f"Error in FeedChain subscriber callback: {e}")

    def drain(self, count: int = 1000) -> List[Article]:
        """
        Drain up to 'count' currently queued articles without blocking.
        Used for initial GUI rendering or batch queries.
        """
        articles: List[Article] = []
        while not self._queue.empty() and len(articles) < count:
            try:
                art = self._queue.get_nowait()
                articles.append(art)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        return articles

    @property
    def size(self) -> int:
        return self._queue.qsize()
