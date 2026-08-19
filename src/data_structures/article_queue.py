"""
Time-based article priority queue with efficient heap operations.

This module provides a specialized priority queue for managing
articles sorted by publication timestamp, optimized for real-time
news streaming applications.

DSA Complexity:
- push: O(log n)
- pop_newest: O(log n)
- get_latest(k): O(k log n)
- peek: O(1)

Space: O(n) where n is number of articles
"""

import heapq
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

# Import Article type
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.types import Article


@dataclass(order=True)
class TimestampedArticle:
    """
    Wrapper for articles with timestamp-based ordering.
    
    Uses negative timestamp for max-heap behavior (most recent first).
    
    Attributes:
        priority: Negative timestamp for max-heap ordering
        counter: Unique counter for stable sorting
        article: The actual Article object
    """
    priority: float  # Negative timestamp (higher = older)
    counter: int = field(compare=True)
    article: Article = field(compare=False)
    
    @classmethod
    def from_article(cls, article: Article, counter: int) -> "TimestampedArticle":
        """Create from Article with automatic priority calculation."""
        # Use published_at or scraped_at, with fallback to epoch
        timestamp = article.published_at or article.scraped_at or datetime.now(UTC)
        
        # Convert to timestamp (negative for max-heap behavior)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        
        priority = -timestamp.timestamp()
        
        return cls(priority=priority, counter=counter, article=article)
    
    @property
    def published_at(self) -> datetime:
        """Get publication datetime."""
        ts = self.article.published_at or self.article.scraped_at
        if ts:
            return ts
        # Reconstruct from priority
        return datetime.fromtimestamp(-self.priority, tz=UTC)


class ArticlePriorityQueue:
    """
    Time-based priority queue for articles using max-heap.
    
    Efficiently maintains articles sorted by publication timestamp,
    enabling O(log n) insertion and O(k log n) retrieval of top k
    most recent articles.
    
    Thread-safe for concurrent access.
    
    Features:
    - Automatic deduplication by article URL
    - Age-based expiry (optional)
    - Statistics tracking
    - Iterator support
    
    Example:
        queue = ArticlePriorityQueue(max_age_hours=24)
        
        # Add articles
        queue.push(article1)
        queue.push(article2)
        queue.push(article3)
        
        # Get 10 most recent
        latest = queue.get_latest(10)
        
        # Iterate in time order
        for article in queue:
            print(f"{article.published_at}: {article.title}")
    
    Time Complexity:
        - push: O(log n)
        - pop_newest: O(log n)
        - get_latest(k): O(k log n)
        - peek: O(1)
        - __contains__: O(1)
        - __len__: O(1)
    
    Space Complexity: O(n)
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        max_age_hours: Optional[int] = None,
        deduplicate: bool = True
    ):
        """
        Initialize the priority queue.
        
        Args:
            max_size: Maximum articles to keep (oldest evicted first)
            max_age_hours: Optional max age for articles (None = no limit)
            deduplicate: Enable URL-based deduplication
        """
        self._heap: List[TimestampedArticle] = []
        self._url_set: Set[str] = set()  # For O(1) deduplication
        self._counter = 0
        self._lock = threading.RLock()
        
        self._max_size = max_size
        self._max_age_hours = max_age_hours
        self._deduplicate = deduplicate
        
        # Statistics
        self._stats = {
            "total_pushed": 0,
            "duplicates_rejected": 0,
            "expired_removed": 0,
            "size_evicted": 0,
        }
    
    def push(self, article: Article) -> bool:
        """
        Add an article to the queue.
        
        Maintains heap property and handles deduplication.
        
        Args:
            article: Article to add
        
        Returns:
            True if article was added, False if duplicate
        """
        with self._lock:
            # Deduplication check
            if self._deduplicate and article.url in self._url_set:
                self._stats["duplicates_rejected"] += 1
                return False
            
            # Age check
            if self._max_age_hours and article.published_at:
                age = datetime.now(UTC) - article.published_at.replace(tzinfo=UTC)
                if age > timedelta(hours=self._max_age_hours):
                    self._stats["expired_removed"] += 1
                    return False
            
            # Create timestamped wrapper
            entry = TimestampedArticle.from_article(article, self._counter)
            self._counter += 1
            
            # Add to heap and URL set
            heapq.heappush(self._heap, entry)
            self._url_set.add(article.url)
            self._stats["total_pushed"] += 1
            
            # Evict oldest if over max size
            while len(self._heap) > self._max_size:
                evicted = heapq.heappop(self._heap)
                self._url_set.discard(evicted.article.url)
                self._stats["size_evicted"] += 1
            
            return True
    
    def push_many(self, articles: List[Article]) -> int:
        """
        Add multiple articles efficiently.
        
        Args:
            articles: List of articles to add
        
        Returns:
            Number of articles successfully added
        """
        added = 0
        for article in articles:
            if self.push(article):
                added += 1
        return added
    
    def pop_newest(self) -> Optional[Article]:
        """
        Remove and return the most recent article.
        
        Returns:
            Most recent Article or None if empty
        """
        with self._lock:
            if not self._heap:
                return None
            
            entry = heapq.heappop(self._heap)
            self._url_set.discard(entry.article.url)
            return entry.article
    
    def peek(self) -> Optional[Article]:
        """
        Get the most recent article without removing it.
        
        Returns:
            Most recent Article or None if empty
        """
        with self._lock:
            if not self._heap:
                return None
            return self._heap[0].article
    
    def get_latest(self, count: int = 10) -> List[Article]:
        """
        Get the k most recent articles without removing them.
        
        Uses partial heap extraction for efficiency.
        
        Args:
            count: Number of articles to return
        
        Returns:
            List of most recent Articles, sorted newest first
        """
        with self._lock:
            if not self._heap:
                return []
            
            # Get smallest (most recent due to negative priority)
            n = min(count, len(self._heap))
            
            # Use nsmallest for partial extraction O(n + k log n)
            entries = heapq.nsmallest(n, self._heap)
            
            return [entry.article for entry in entries]
    
    def get_in_time_range(
        self,
        start: datetime,
        end: Optional[datetime] = None
    ) -> List[Article]:
        """
        Get articles within a time range.
        
        Args:
            start: Start datetime (inclusive)
            end: End datetime (exclusive), defaults to now
        
        Returns:
            Articles in time range, sorted newest first
        """
        with self._lock:
            if not self._heap:
                return []
            
            if end is None:
                end = datetime.now(UTC)
            
            # Ensure timezone awareness
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            
            results = []
            for entry in self._heap:
                pub_time = entry.published_at
                if pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=UTC)
                
                if start <= pub_time < end:
                    results.append(entry)
            
            # Sort by priority (newest first)
            results.sort(key=lambda x: x.priority)
            
            return [entry.article for entry in results]
    
    def get_last_n_hours(self, hours: int = 24) -> List[Article]:
        """
        Get articles from the last N hours.
        
        Args:
            hours: Number of hours to look back
        
        Returns:
            Articles from last N hours, sorted newest first
        """
        now = datetime.now(UTC)
        start = now - timedelta(hours=hours)
        return self.get_in_time_range(start, now)
    
    def remove_expired(self) -> int:
        """
        Remove articles older than max_age_hours.
        
        Returns:
            Number of articles removed
        """
        if not self._max_age_hours:
            return 0
        
        with self._lock:
            cutoff = datetime.now(UTC) - timedelta(hours=self._max_age_hours)
            
            # Rebuild heap without expired entries
            new_heap = []
            removed = 0
            
            for entry in self._heap:
                pub_time = entry.published_at
                if pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=UTC)
                
                if pub_time >= cutoff:
                    new_heap.append(entry)
                else:
                    self._url_set.discard(entry.article.url)
                    removed += 1
            
            if removed > 0:
                heapq.heapify(new_heap)
                self._heap = new_heap
                self._stats["expired_removed"] += removed
            
            return removed
    
    def contains_url(self, url: str) -> bool:
        """Check if URL is already in queue."""
        return url in self._url_set
    
    def clear(self) -> None:
        """Remove all articles from the queue."""
        with self._lock:
            self._heap.clear()
            self._url_set.clear()
    
    def __contains__(self, article: Article) -> bool:
        """Check if article is in queue (by URL)."""
        return article.url in self._url_set
    
    def __len__(self) -> int:
        """Return number of articles in queue."""
        return len(self._heap)
    
    def __bool__(self) -> bool:
        """Return True if queue is not empty."""
        return len(self._heap) > 0
    
    def __iter__(self) -> Iterator[Article]:
        """Iterate over articles in time order (newest first)."""
        with self._lock:
            sorted_entries = sorted(self._heap, key=lambda x: x.priority)
            for entry in sorted_entries:
                yield entry.article
    
    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._heap) == 0
    
    @property
    def oldest_timestamp(self) -> Optional[datetime]:
        """Get timestamp of oldest article."""
        with self._lock:
            if not self._heap:
                return None
            
            # Find max priority (oldest, since priority is negative)
            oldest = max(self._heap, key=lambda x: x.priority)
            return oldest.published_at
    
    @property
    def newest_timestamp(self) -> Optional[datetime]:
        """Get timestamp of newest article."""
        with self._lock:
            if not self._heap:
                return None
            return self._heap[0].published_at
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            **self._stats,
            "current_size": len(self._heap),
            "max_size": self._max_size,
            "oldest": self.oldest_timestamp.isoformat() if self.oldest_timestamp else None,
            "newest": self.newest_timestamp.isoformat() if self.newest_timestamp else None,
        }


class ArticleTimeIndex:
    """
    Secondary index for time-range queries.
    
    Uses a sorted list with binary search for efficient
    time-range lookups.
    
    Time Complexity:
        - insert: O(n) (maintains sorted order)
        - range_query: O(log n + k) where k is result size
    """
    
    def __init__(self):
        """Initialize empty index."""
        self._entries: List[Tuple[datetime, str]] = []  # (timestamp, url)
        self._url_to_idx: Dict[str, int] = {}
        self._lock = threading.Lock()
    
    def insert(self, article: Article) -> None:
        """Insert article into index."""
        timestamp = article.published_at or article.scraped_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        
        with self._lock:
            # Binary search for insertion point
            import bisect
            idx = bisect.bisect_left(
                self._entries,
                (timestamp, article.url),
                key=lambda x: x[0]
            )
            self._entries.insert(idx, (timestamp, article.url))
            
            # Update index positions
            for i, (_, url) in enumerate(self._entries):
                self._url_to_idx[url] = i
    
    def range_query(
        self,
        start: datetime,
        end: datetime
    ) -> List[str]:
        """
        Get article URLs in time range.
        
        Args:
            start: Start datetime (inclusive)
            end: End datetime (exclusive)
        
        Returns:
            List of URLs in time range
        """
        import bisect
        
        with self._lock:
            if not self._entries:
                return []
            
            # Binary search for range bounds
            start_idx = bisect.bisect_left(
                self._entries,
                (start,),
                key=lambda x: x[0]
            )
            end_idx = bisect.bisect_left(
                self._entries,
                (end,),
                key=lambda x: x[0]
            )
            
            return [url for _, url in self._entries[start_idx:end_idx]]
    
    def remove(self, url: str) -> bool:
        """Remove article from index."""
        with self._lock:
            if url not in self._url_to_idx:
                return False
            
            idx = self._url_to_idx[url]
            del self._entries[idx]
            del self._url_to_idx[url]
            
            # Update remaining indices
            for i, (_, u) in enumerate(self._entries):
                self._url_to_idx[u] = i
            
            return True
    
    def clear(self) -> None:
        """Clear the index."""
        with self._lock:
            self._entries.clear()
            self._url_to_idx.clear()
    
    def __len__(self) -> int:
        return len(self._entries)
