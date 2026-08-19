"""
LRU Cache with TTL support for HTTP response caching.

This implementation provides:
- O(1) get/set operations using dict + doubly linked list
- Time-based expiration (TTL)
- Memory-efficient design
- Thread-safe operations
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, TypeVar

K = TypeVar('K')
V = TypeVar('V')


@dataclass
class CacheEntry(Generic[V]):
    """
    Entry in the LRU cache.
    
    Attributes:
        value: Cached value
        created_at: Timestamp when entry was created
        expires_at: Timestamp when entry expires (None = never)
        hits: Number of times this entry was accessed
    """
    value: V
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    hits: int = 0
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at


class _Node(Generic[K, V]):
    """Doubly linked list node for LRU tracking."""
    
    __slots__ = ('key', 'entry', 'prev', 'next')
    
    def __init__(
        self,
        key: K,
        entry: CacheEntry[V],
        prev: Optional["_Node[K, V]"] = None,
        next: Optional["_Node[K, V]"] = None
    ) -> None:
        self.key = key
        self.entry = entry
        self.prev = prev
        self.next = next


class LRUCache(Generic[K, V]):
    """
    Least Recently Used (LRU) Cache with TTL support.
    
    Implements O(1) operations using a hash map for fast lookups
    and a doubly linked list for LRU ordering.
    
    Example:
        cache = LRUCache[str, dict](max_size=1000, default_ttl=300)
        
        # Cache HTTP response for 5 minutes
        cache.set("https://example.com", response_data, ttl=300)
        
        # Get cached response
        response = cache.get("https://example.com")
        if response is not None:
            # Cache hit
            return response
    
    Time Complexity:
        - get: O(1)
        - set: O(1)
        - delete: O(1)
    
    Space Complexity: O(n) where n is max_size
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: Optional[int] = None
    ) -> None:
        """
        Initialize the LRU cache.
        
        Args:
            max_size: Maximum number of entries to store
            default_ttl: Default time-to-live in seconds (None = no expiry)
        """
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        
        self._max_size = max_size
        self._default_ttl = default_ttl
        
        # HashMap for O(1) lookup
        self._cache: Dict[K, _Node[K, V]] = {}
        
        # Doubly linked list for LRU ordering
        # head = most recent, tail = least recent
        self._head: Optional[_Node[K, V]] = None
        self._tail: Optional[_Node[K, V]] = None
        
        # Statistics
        self._hits = 0
        self._misses = 0
        
        # Thread safety
        self._lock = threading.RLock()
    
    def get(self, key: K) -> Optional[V]:
        """
        Get a value from the cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            node = self._cache.get(key)
            
            if node is None:
                self._misses += 1
                return None
            
            # Check expiration
            if node.entry.is_expired:
                self._remove_node(node)
                del self._cache[key]
                self._misses += 1
                return None
            
            # Update statistics
            node.entry.hits += 1
            self._hits += 1
            
            # Move to front (most recently used)
            self._move_to_front(node)
            
            return node.entry.value
    
    def set(
        self,
        key: K,
        value: V,
        ttl: Optional[int] = None
    ) -> None:
        """
        Set a value in the cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (overrides default_ttl)
        """
        with self._lock:
            # Calculate expiration time
            expires_at = None
            effective_ttl = ttl if ttl is not None else self._default_ttl
            if effective_ttl is not None:
                expires_at = time.time() + effective_ttl
            
            # Create entry
            entry = CacheEntry(value=value, expires_at=expires_at)
            
            # Check if key exists
            existing = self._cache.get(key)
            if existing is not None:
                # Update existing entry
                existing.entry = entry
                self._move_to_front(existing)
            else:
                # Create new node
                node = _Node(key=key, entry=entry)
                self._cache[key] = node
                self._add_to_front(node)
                
                # Evict if over capacity
                while len(self._cache) > self._max_size:
                    self._evict_lru()
    
    def delete(self, key: K) -> bool:
        """
        Delete a key from the cache.
        
        Args:
            key: Cache key to delete
        
        Returns:
            True if key was deleted, False if not found
        """
        with self._lock:
            node = self._cache.get(key)
            if node is None:
                return False
            
            self._remove_node(node)
            del self._cache[key]
            return True
    
    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
            self._head = None
            self._tail = None
    
    def _add_to_front(self, node: _Node[K, V]) -> None:
        """Add node to front of list (most recent)."""
        node.prev = None
        node.next = self._head
        
        if self._head is not None:
            self._head.prev = node
        
        self._head = node
        
        if self._tail is None:
            self._tail = node
    
    def _remove_node(self, node: _Node[K, V]) -> None:
        """Remove node from list."""
        if node.prev is not None:
            node.prev.next = node.next
        else:
            self._head = node.next
        
        if node.next is not None:
            node.next.prev = node.prev
        else:
            self._tail = node.prev
    
    def _move_to_front(self, node: _Node[K, V]) -> None:
        """Move existing node to front."""
        self._remove_node(node)
        self._add_to_front(node)
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if self._tail is not None:
            del self._cache[self._tail.key]
            self._remove_node(self._tail)
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key, node in self._cache.items()
                if node.entry.is_expired
            ]
            
            for key in expired_keys:
                node = self._cache[key]
                self._remove_node(node)
                del self._cache[key]
            
            return len(expired_keys)
    
    def __contains__(self, key: K) -> bool:
        """Check if key is in cache (doesn't update LRU order)."""
        with self._lock:
            node = self._cache.get(key)
            if node is None:
                return False
            return not node.entry.is_expired
    
    def __len__(self) -> int:
        """Return number of entries in cache."""
        return len(self._cache)
    
    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)
    
    @property
    def max_size(self) -> int:
        """Get maximum cache size."""
        return self._max_size
    
    @property
    def hit_rate(self) -> float:
        """Get cache hit rate."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "default_ttl": self._default_ttl,
        }
    
    def __repr__(self) -> str:
        return (
            f"LRUCache(size={len(self._cache)}/{self._max_size}, "
            f"hit_rate={self.hit_rate:.1%})"
        )


class HTTPResponseCache:
    """
    Specialized LRU cache for HTTP responses.
    
    Provides URL-specific caching with automatic response
    parsing and size limits.
    """
    
    def __init__(
        self,
        max_responses: int = 500,
        default_ttl: int = 300,  # 5 minutes
        max_response_size: int = 5 * 1024 * 1024  # 5MB
    ) -> None:
        """
        Initialize HTTP response cache.
        
        Args:
            max_responses: Maximum number of responses to cache
            default_ttl: Default TTL in seconds
            max_response_size: Maximum response size to cache
        """
        self._cache = LRUCache[str, Dict[str, Any]](
            max_size=max_responses,
            default_ttl=default_ttl
        )
        self._max_response_size = max_response_size
    
    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """Get cached response for URL."""
        return self._cache.get(url)
    
    def set(
        self,
        url: str,
        status_code: int,
        content: str,
        headers: Optional[Dict[str, str]] = None,
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache an HTTP response.
        
        Args:
            url: Request URL
            status_code: HTTP status code
            content: Response content
            headers: Response headers
            ttl: Custom TTL in seconds
        """
        # Check size limit
        if len(content) > self._max_response_size:
            return
        
        response = {
            "url": url,
            "status_code": status_code,
            "content": content,
            "headers": headers or {},
            "cached_at": time.time(),
        }
        
        self._cache.set(url, response, ttl)
    
    def invalidate(self, url: str) -> bool:
        """Invalidate cached response for URL."""
        return self._cache.delete(url)
    
    def clear(self) -> None:
        """Clear all cached responses."""
        self._cache.clear()
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.stats
