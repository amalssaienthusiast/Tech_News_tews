"""
Scrape Queue with History and Statistics.

Provides:
- URL queue with priority
- Already-scraped URL tracking (prevents re-scraping within cooldown)
- Statistics tracking (success/failure rates, per-domain stats)
- Persistent history to JSON file

Usage:
    queue = ScrapeQueue()
    
    # Add URLs
    queue.add_to_queue("https://example.com/article1", priority=1)
    
    # Check if recently scraped
    if not queue.already_scraped("https://example.com/article1"):
        # Scrape it
        ...
    
    # Record result
    queue.record_result("https://example.com/article1", success=True, articles_found=5)
    
    # Get statistics
    stats = queue.get_statistics()
"""

import asyncio
import json
import logging
import time
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from dataclasses import dataclass, field, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class QueueItem:
    """An item in the scrape queue."""
    url: str
    priority: int = 1  # Lower = higher priority
    added_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    retries: int = 0
    
    def __lt__(self, other):
        """Enable heap comparison by priority."""
        return self.priority < other.priority


@dataclass
class ScrapeRecord:
    """Record of a completed scrape attempt."""
    url: str
    timestamp: datetime
    success: bool
    duration_ms: float
    articles_found: int = 0
    error: Optional[str] = None
    domain: str = ""
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "duration_ms": self.duration_ms,
            "articles_found": self.articles_found,
            "error": self.error,
            "domain": self.domain,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ScrapeRecord":
        return cls(
            url=data["url"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            success=data["success"],
            duration_ms=data["duration_ms"],
            articles_found=data.get("articles_found", 0),
            error=data.get("error"),
            domain=data.get("domain", ""),
        )


# =============================================================================
# SCRAPE QUEUE
# =============================================================================

class ScrapeQueue:
    """
    Manages scraping queue with history and statistics.
    
    Features:
    - Priority-based URL queue
    - URL deduplication (prevents re-scraping within cooldown)
    - Per-domain rate limiting
    - Statistics tracking
    - Persistent history
    """
    
    DEFAULT_COOLDOWN_SECONDS = 3600  # 1 hour
    MAX_HISTORY = 1000  # Max records to keep
    
    def __init__(
        self,
        history_file: Optional[str] = None,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        max_workers: int = 3,
    ):
        """
        Initialize the scrape queue.
        
        Args:
            history_file: Path to JSON file for persistent history
            cooldown_seconds: Seconds before URL can be re-scraped
            max_workers: Max concurrent scrape workers
        """
        self._cooldown_seconds = cooldown_seconds
        self._max_workers = max_workers
        
        # Queue storage (using list as priority queue)
        self._queue: List[QueueItem] = []
        self._queue_urls: set = set()  # Fast URL lookup
        
        # History storage
        self._history: List[ScrapeRecord] = []
        self._url_last_scraped: Dict[str, datetime] = {}  # URL -> last scrape time
        
        # Statistics
        self._stats = {
            "total_scrapes": 0,
            "successful": 0,
            "failed": 0,
            "total_articles": 0,
            "by_domain": defaultdict(lambda: {"success": 0, "failed": 0, "articles": 0}),
            "by_hour": defaultdict(int),  # Hour -> scrape count
        }
        
        # History file
        self._history_file = Path(history_file) if history_file else None
        if self._history_file:
            self._load_history()
        
        logger.info(f"ScrapeQueue initialized (cooldown={cooldown_seconds}s, workers={max_workers})")
    
    # =========================================================================
    # QUEUE OPERATIONS
    # =========================================================================
    
    def add_to_queue(self, url: str, priority: int = 1) -> bool:
        """
        Add URL to scrape queue.
        
        Args:
            url: URL to scrape
            priority: Lower = higher priority (1 = highest)
        
        Returns:
            True if added, False if already in queue or recently scraped
        """
        # Skip if already queued
        if url in self._queue_urls:
            logger.debug(f"URL already in queue: {url[:50]}...")
            return False
        
        # Skip if recently scraped
        if self.already_scraped(url):
            logger.debug(f"URL recently scraped: {url[:50]}...")
            return False
        
        # Add to queue
        item = QueueItem(url=url, priority=priority)
        self._queue.append(item)
        self._queue_urls.add(url)
        
        # Sort by priority (lower = higher priority)
        self._queue.sort(key=lambda x: x.priority)
        
        logger.debug(f"Added to queue: {url[:50]}... (priority={priority})")
        return True
    
    def get_next(self) -> Optional[str]:
        """Get next URL to scrape (removes from queue)."""
        if not self._queue:
            return None
        
        item = self._queue.pop(0)
        self._queue_urls.discard(item.url)
        return item.url
    
    def peek(self) -> Optional[str]:
        """Peek at next URL without removing."""
        return self._queue[0].url if self._queue else None
    
    @property
    def size(self) -> int:
        """Current queue size."""
        return len(self._queue)
    
    def clear(self):
        """Clear the queue."""
        self._queue.clear()
        self._queue_urls.clear()
    
    # =========================================================================
    # COOLDOWN & DEDUPLICATION
    # =========================================================================
    
    def already_scraped(self, url: str) -> bool:
        """
        Check if URL was recently scraped (within cooldown).
        
        Args:
            url: URL to check
        
        Returns:
            True if scraped within cooldown period
        """
        last_scraped = self._url_last_scraped.get(url)
        if not last_scraped:
            return False
        
        elapsed = (datetime.now(UTC) - last_scraped).total_seconds()
        return elapsed < self._cooldown_seconds
    
    def get_cooldown_remaining(self, url: str) -> int:
        """Get seconds remaining in cooldown for URL."""
        last_scraped = self._url_last_scraped.get(url)
        if not last_scraped:
            return 0
        
        elapsed = (datetime.now(UTC) - last_scraped).total_seconds()
        remaining = self._cooldown_seconds - elapsed
        return max(0, int(remaining))
    
    # =========================================================================
    # RECORDING RESULTS
    # =========================================================================
    
    def record_result(
        self,
        url: str,
        success: bool,
        duration_ms: float = 0,
        articles_found: int = 0,
        error: Optional[str] = None,
    ):
        """
        Record the result of a scrape attempt.
        
        Args:
            url: URL that was scraped
            success: Whether scrape succeeded
            duration_ms: Time taken in milliseconds
            articles_found: Number of articles found
            error: Error message if failed
        """
        now = datetime.now(UTC)
        domain = urlparse(url).netloc
        
        # Create record
        record = ScrapeRecord(
            url=url,
            timestamp=now,
            success=success,
            duration_ms=duration_ms,
            articles_found=articles_found,
            error=error,
            domain=domain,
        )
        
        # Add to history
        self._history.append(record)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)
        
        # Update URL tracking
        self._url_last_scraped[url] = now
        
        # Update statistics
        self._stats["total_scrapes"] += 1
        if success:
            self._stats["successful"] += 1
            self._stats["total_articles"] += articles_found
            self._stats["by_domain"][domain]["success"] += 1
            self._stats["by_domain"][domain]["articles"] += articles_found
        else:
            self._stats["failed"] += 1
            self._stats["by_domain"][domain]["failed"] += 1
        
        # Track by hour
        hour_key = now.strftime("%Y-%m-%d %H:00")
        self._stats["by_hour"][hour_key] += 1
        
        # Persist
        if self._history_file:
            self._save_history()
        
        logger.debug(f"Recorded: {url[:40]}... success={success} articles={articles_found}")
    
    # =========================================================================
    # STATISTICS
    # =========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive scraping statistics.
        
        Returns:
            Dict with statistics including:
            - queue_size: Current queue size
            - total_scrapes: Total scrape attempts
            - successful: Successful scrapes
            - failed: Failed scrapes
            - success_rate: Percentage success rate
            - total_articles: Total articles found
            - by_domain: Per-domain breakdown
            - recent_history: Last 10 scrape records
        """
        total = self._stats["total_scrapes"]
        success_rate = (self._stats["successful"] / total * 100) if total > 0 else 0
        
        return {
            "queue_size": len(self._queue),
            "cooldown_seconds": self._cooldown_seconds,
            "total_scrapes": total,
            "successful": self._stats["successful"],
            "failed": self._stats["failed"],
            "success_rate": round(success_rate, 1),
            "total_articles": self._stats["total_articles"],
            "by_domain": dict(self._stats["by_domain"]),
            "by_hour": dict(self._stats["by_hour"]),
            "recent_history": [r.to_dict() for r in self._history[-10:]],
            "urls_tracked": len(self._url_last_scraped),
        }
    
    def get_domain_stats(self, domain: str) -> Dict[str, int]:
        """Get statistics for a specific domain."""
        return dict(self._stats["by_domain"].get(domain, {"success": 0, "failed": 0, "articles": 0}))
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _load_history(self):
        """Load history from file."""
        if not self._history_file or not self._history_file.exists():
            return
        
        try:
            with open(self._history_file, 'r') as f:
                data = json.load(f)
            
            self._history = [ScrapeRecord.from_dict(r) for r in data.get("history", [])]
            self._url_last_scraped = {
                r.url: r.timestamp for r in self._history
            }
            
            # Restore stats
            saved_stats = data.get("stats", {})
            self._stats["total_scrapes"] = saved_stats.get("total_scrapes", 0)
            self._stats["successful"] = saved_stats.get("successful", 0)
            self._stats["failed"] = saved_stats.get("failed", 0)
            self._stats["total_articles"] = saved_stats.get("total_articles", 0)
            
            logger.info(f"Loaded {len(self._history)} history records from {self._history_file}")
            
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
    
    def _save_history(self):
        """Save history to file."""
        if not self._history_file:
            return
        
        try:
            # Ensure directory exists
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "history": [r.to_dict() for r in self._history[-self.MAX_HISTORY:]],
                "stats": {
                    "total_scrapes": self._stats["total_scrapes"],
                    "successful": self._stats["successful"],
                    "failed": self._stats["failed"],
                    "total_articles": self._stats["total_articles"],
                },
                "saved_at": datetime.now(UTC).isoformat(),
            }
            
            with open(self._history_file, 'w') as f:
                json.dump(data, f, indent=2)
            
        except Exception as e:
            logger.warning(f"Failed to save history: {e}")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_scrape_queue: Optional[ScrapeQueue] = None


def get_scrape_queue(
    history_file: Optional[str] = None,
    cooldown_seconds: int = ScrapeQueue.DEFAULT_COOLDOWN_SECONDS,
) -> ScrapeQueue:
    """
    Get singleton ScrapeQueue instance.
    
    Args:
        history_file: Path to history file (only used on first call)
        cooldown_seconds: Cooldown between re-scrapes (only used on first call)
    
    Returns:
        ScrapeQueue singleton instance
    """
    global _scrape_queue
    if _scrape_queue is None:
        # Default history file in data directory
        if history_file is None:
            project_root = Path(__file__).parent.parent.parent
            history_file = str(project_root / "data" / "scrape_history.json")
        
        _scrape_queue = ScrapeQueue(
            history_file=history_file,
            cooldown_seconds=cooldown_seconds,
        )
    
    return _scrape_queue
