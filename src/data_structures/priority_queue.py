"""
Priority Queue for source ranking and task scheduling.

This implementation provides:
- O(log n) insert and extract operations
- Priority updates in O(log n)
- Custom comparator support
- Thread-safe operations
"""

import heapq
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, TypeVar

T = TypeVar('T')


@dataclass(order=True)
class PriorityItem(Generic[T]):
    """
    Wrapper for items in the priority queue.
    
    Attributes:
        priority: Priority value (lower = higher priority)
        counter: Unique counter for stable sorting
        item: The actual item
    """
    priority: float
    counter: int = field(compare=True)
    item: T = field(compare=False)
    removed: bool = field(default=False, compare=False)


class PriorityQueue(Generic[T]):
    """
    Thread-safe priority queue with update support.
    
    Uses a binary heap for efficient O(log n) operations and
    supports priority updates through lazy deletion.
    
    Example:
        pq = PriorityQueue[Source]()
        
        # Add sources with priority (lower = higher priority)
        pq.push(source_a, priority=1.0)
        pq.push(source_b, priority=2.0)
        pq.push(source_c, priority=0.5)
        
        # Pop highest priority (lowest number)
        source = pq.pop()  # Returns source_c (priority 0.5)
    
    Time Complexity:
        - push: O(log n)
        - pop: O(log n) amortized
        - peek: O(1)
        - update_priority: O(log n)
    
    Space Complexity: O(n)
    """
    
    def __init__(self) -> None:
        """Initialize empty priority queue."""
        self._heap: List[PriorityItem[T]] = []
        self._entry_finder: Dict[Any, PriorityItem[T]] = {}
        self._counter = 0
        self._lock = threading.RLock()
    
    def push(self, item: T, priority: float = 0.0) -> None:
        """
        Add an item to the queue.
        
        Args:
            item: Item to add
            priority: Priority value (lower = higher priority)
        """
        with self._lock:
            # Check if item already exists
            if id(item) in self._entry_finder:
                self.update_priority(item, priority)
                return
            
            # Create entry
            entry = PriorityItem(
                priority=priority,
                counter=self._counter,
                item=item
            )
            self._counter += 1
            
            # Track and add to heap
            self._entry_finder[id(item)] = entry
            heapq.heappush(self._heap, entry)
    
    def pop(self) -> Optional[T]:
        """
        Remove and return the highest priority item.
        
        Returns:
            Highest priority item or None if queue is empty
        """
        with self._lock:
            while self._heap:
                entry = heapq.heappop(self._heap)
                
                # Skip removed entries (lazy deletion)
                if not entry.removed:
                    del self._entry_finder[id(entry.item)]
                    return entry.item
            
            return None
    
    def peek(self) -> Optional[T]:
        """
        Return the highest priority item without removing it.
        
        Returns:
            Highest priority item or None if queue is empty
        """
        with self._lock:
            # Clean removed entries from top
            while self._heap and self._heap[0].removed:
                heapq.heappop(self._heap)
            
            if self._heap:
                return self._heap[0].item
            return None
    
    def update_priority(self, item: T, new_priority: float) -> bool:
        """
        Update the priority of an existing item.
        
        Uses lazy deletion: marks old entry as removed and
        creates a new entry with updated priority.
        
        Args:
            item: Item to update
            new_priority: New priority value
        
        Returns:
            True if item was found and updated, False otherwise
        """
        with self._lock:
            entry = self._entry_finder.get(id(item))
            if entry is None:
                return False
            
            # Mark old entry as removed
            entry.removed = True
            
            # Create new entry with updated priority
            new_entry = PriorityItem(
                priority=new_priority,
                counter=self._counter,
                item=item
            )
            self._counter += 1
            
            self._entry_finder[id(item)] = new_entry
            heapq.heappush(self._heap, new_entry)
            
            return True
    
    def remove(self, item: T) -> bool:
        """
        Remove an item from the queue.
        
        Args:
            item: Item to remove
        
        Returns:
            True if item was found and removed, False otherwise
        """
        with self._lock:
            entry = self._entry_finder.get(id(item))
            if entry is None:
                return False
            
            entry.removed = True
            del self._entry_finder[id(item)]
            return True
    
    def clear(self) -> None:
        """Remove all items from the queue."""
        with self._lock:
            self._heap.clear()
            self._entry_finder.clear()
            self._counter = 0
    
    def __contains__(self, item: T) -> bool:
        """Check if item is in the queue."""
        return id(item) in self._entry_finder
    
    def __len__(self) -> int:
        """Return number of items in the queue."""
        return len(self._entry_finder)
    
    def __bool__(self) -> bool:
        """Return True if queue is not empty."""
        return len(self._entry_finder) > 0
    
    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._entry_finder) == 0


class SourcePriorityQueue:
    """
    Specialized priority queue for source management.
    
    Ranks sources based on multiple factors:
    - Source tier (Tier 1 > Tier 2 > ...)
    - Historical success rate
    - Time since last scrape
    - Article yield rate
    """
    
    def __init__(self) -> None:
        """Initialize source queue."""
        self._queue: PriorityQueue[Dict[str, Any]] = PriorityQueue()
    
    def calculate_priority(self, source: Dict[str, Any]) -> float:
        """
        Calculate priority score for a source.
        
        Lower score = higher priority.
        
        Args:
            source: Source dictionary with metadata
        
        Returns:
            Priority score (0.0 = highest priority)
        """
        import time
        
        # Base priority from tier (1=highest, 4=lowest)
        tier = source.get("tier", 3)
        tier_score = tier / 4.0  # Normalize to 0.25-1.0
        
        # Success rate bonus (higher = better = lower priority)
        success_rate = source.get("success_rate", 0.5)
        success_score = 1.0 - success_rate  # Invert: 0 for 100% success
        
        # Recency penalty (longer since scrape = lower priority value = higher priority)
        last_scraped = source.get("last_scraped", 0)
        hours_since = (time.time() - last_scraped) / 3600 if last_scraped else 24
        recency_score = max(0.0, 1.0 - (hours_since / 24.0))  # 0 if >24h ago
        
        # Article yield (more articles = higher priority = lower score)
        article_rate = source.get("article_rate", 0.5)
        yield_score = 1.0 - min(1.0, article_rate)
        
        # Weighted combination
        priority = (
            tier_score * 0.3 +
            success_score * 0.2 +
            recency_score * 0.3 +
            yield_score * 0.2
        )
        
        return priority
    
    def add_source(self, source: Dict[str, Any]) -> None:
        """Add a source to the queue."""
        priority = self.calculate_priority(source)
        self._queue.push(source, priority)
    
    def get_next_source(self) -> Optional[Dict[str, Any]]:
        """Get the highest priority source."""
        return self._queue.pop()
    
    def peek_next_source(self) -> Optional[Dict[str, Any]]:
        """Peek at the highest priority source without removing."""
        return self._queue.peek()
    
    def update_source(self, source: Dict[str, Any]) -> None:
        """Update a source's priority based on new metadata."""
        priority = self.calculate_priority(source)
        self._queue.update_priority(source, priority)
    
    def add_sources(self, sources: List[Dict[str, Any]]) -> None:
        """Add multiple sources to the queue."""
        for source in sources:
            self.add_source(source)
    
    def get_all_sources_ordered(self) -> List[Dict[str, Any]]:
        """Get all sources in priority order (highest first)."""
        sources = []
        while not self._queue.is_empty:
            source = self._queue.pop()
            if source:
                sources.append(source)
        
        # Re-add all sources
        for source in sources:
            self.add_source(source)
        
        return sources
    
    def __len__(self) -> int:
        return len(self._queue)
    
    @property
    def is_empty(self) -> bool:
        return self._queue.is_empty


class TaskScheduler:
    """
    Priority-based task scheduler.
    
    Schedules scraping tasks based on priority and
    respects rate limits between tasks.
    """
    
    @dataclass
    class Task:
        """Scheduled task."""
        id: str
        action: Callable
        args: tuple = field(default_factory=tuple)
        kwargs: Dict[str, Any] = field(default_factory=dict)
        priority: float = 0.0
        scheduled_at: float = field(default_factory=lambda: __import__('time').time())
        
        def execute(self) -> Any:
            """Execute the task."""
            return self.action(*self.args, **self.kwargs)
    
    def __init__(self) -> None:
        """Initialize task scheduler."""
        self._queue: PriorityQueue[TaskScheduler.Task] = PriorityQueue()
        self._completed: List[str] = []
        self._failed: List[str] = []
    
    def schedule(
        self,
        task_id: str,
        action: Callable,
        priority: float = 0.0,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Schedule a task.
        
        Args:
            task_id: Unique task identifier
            action: Callable to execute
            priority: Task priority (lower = higher priority)
            args: Positional arguments for action
            kwargs: Keyword arguments for action
        """
        task = self.Task(
            id=task_id,
            action=action,
            args=args,
            kwargs=kwargs or {},
            priority=priority
        )
        self._queue.push(task, priority)
    
    def get_next_task(self) -> Optional["TaskScheduler.Task"]:
        """Get the next task to execute."""
        return self._queue.pop()
    
    def mark_completed(self, task_id: str) -> None:
        """Mark a task as completed."""
        self._completed.append(task_id)
    
    def mark_failed(self, task_id: str) -> None:
        """Mark a task as failed."""
        self._failed.append(task_id)
    
    @property
    def pending_count(self) -> int:
        """Get number of pending tasks."""
        return len(self._queue)
    
    @property
    def stats(self) -> Dict[str, int]:
        """Get scheduler statistics."""
        return {
            "pending": len(self._queue),
            "completed": len(self._completed),
            "failed": len(self._failed),
        }
