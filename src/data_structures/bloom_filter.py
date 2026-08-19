"""
Bloom Filter for probabilistic URL deduplication.

A Bloom filter is a space-efficient probabilistic data structure that
tests whether an element is a member of a set. False positives are
possible but false negatives are not.

This implementation provides:
- O(k) insert and lookup (k = number of hash functions)
- Memory-efficient storage for millions of URLs
- Configurable false positive rate
- Serialization support
"""

import hashlib
import math
from typing import List, Optional


class BloomFilter:
    """
    Memory-efficient probabilistic set for URL deduplication.
    
    Uses multiple hash functions to minimize false positives while
    maintaining O(1) insertion and lookup times.
    
    Example:
        # Create filter for 100k items with 1% false positive rate
        bloom = BloomFilter(expected_items=100_000, false_positive_rate=0.01)
        
        bloom.add("https://example.com/article-1")
        bloom.add("https://example.com/article-2")
        
        "https://example.com/article-1" in bloom  # True
        "https://example.com/new-article" in bloom  # False (probably)
    
    Time Complexity: O(k) for both add and contains
    Space Complexity: O(m) bits where m is determined by expected_items
                      and false_positive_rate
    """
    
    def __init__(
        self,
        expected_items: int = 100_000,
        false_positive_rate: float = 0.01
    ) -> None:
        """
        Initialize the Bloom filter.
        
        Args:
            expected_items: Expected number of items to store
            false_positive_rate: Desired false positive rate (0.0 to 1.0)
        
        Raises:
            ValueError: If parameters are out of valid range
        """
        if expected_items <= 0:
            raise ValueError("expected_items must be positive")
        if not 0.0 < false_positive_rate < 1.0:
            raise ValueError("false_positive_rate must be between 0 and 1")
        
        self._expected_items = expected_items
        self._false_positive_rate = false_positive_rate
        
        # Calculate optimal bit array size and hash count
        # m = -n * ln(p) / (ln(2)^2)
        self._size = self._calculate_size(expected_items, false_positive_rate)
        
        # k = (m/n) * ln(2)
        self._hash_count = self._calculate_hash_count(
            self._size, expected_items
        )
        
        # Initialize bit array as integer (Python handles arbitrary precision)
        self._bit_array = 0
        self._item_count = 0
    
    @staticmethod
    def _calculate_size(n: int, p: float) -> int:
        """Calculate optimal bit array size."""
        m = -n * math.log(p) / (math.log(2) ** 2)
        return int(math.ceil(m))
    
    @staticmethod
    def _calculate_hash_count(m: int, n: int) -> int:
        """Calculate optimal number of hash functions."""
        k = (m / n) * math.log(2)
        return max(1, int(round(k)))
    
    def _get_hash_values(self, item: str) -> List[int]:
        """
        Generate k hash values for an item.
        
        Uses double hashing technique: h(i) = h1 + i*h2
        to generate k hash values from just 2 hash computations.
        """
        # Convert to bytes if string
        item_bytes = item.encode("utf-8")
        
        # Generate two base hashes
        h1 = int(hashlib.md5(item_bytes).hexdigest(), 16)
        h2 = int(hashlib.sha256(item_bytes).hexdigest(), 16)
        
        # Generate k hash values using double hashing
        return [(h1 + i * h2) % self._size for i in range(self._hash_count)]
    
    def add(self, item: str) -> None:
        """
        Add an item to the filter.
        
        Args:
            item: Item (URL) to add
        """
        for position in self._get_hash_values(item):
            self._bit_array |= (1 << position)
        
        self._item_count += 1
    
    def __contains__(self, item: str) -> bool:
        """
        Check if item might be in the filter.
        
        Args:
            item: Item to check
        
        Returns:
            True if item might be in filter (can be false positive)
            False if item is definitely not in filter
        """
        for position in self._get_hash_values(item):
            if not (self._bit_array & (1 << position)):
                return False
        return True
    
    def might_contain(self, item: str) -> bool:
        """Alias for __contains__."""
        return item in self
    
    def definitely_not_contains(self, item: str) -> bool:
        """Check if item is definitely not in filter (no false negatives)."""
        return item not in self
    
    @property
    def size_bits(self) -> int:
        """Get bit array size."""
        return self._size
    
    @property
    def size_bytes(self) -> int:
        """Get approximate size in bytes."""
        return self._size // 8 + 1
    
    @property
    def size_kb(self) -> float:
        """Get approximate size in kilobytes."""
        return self.size_bytes / 1024
    
    @property
    def hash_count(self) -> int:
        """Get number of hash functions used."""
        return self._hash_count
    
    @property
    def item_count(self) -> int:
        """Get number of items added."""
        return self._item_count
    
    @property
    def fill_ratio(self) -> float:
        """Get ratio of set bits to total bits."""
        set_bits = bin(self._bit_array).count('1')
        return set_bits / self._size if self._size > 0 else 0.0
    
    def estimated_false_positive_rate(self) -> float:
        """
        Calculate current estimated false positive rate.
        
        As the filter fills up, the false positive rate increases.
        """
        # p = (1 - e^(-kn/m))^k
        if self._item_count == 0:
            return 0.0
        
        exponent = -self._hash_count * self._item_count / self._size
        return (1 - math.exp(exponent)) ** self._hash_count
    
    def clear(self) -> None:
        """Clear all items from the filter."""
        self._bit_array = 0
        self._item_count = 0
    
    def merge(self, other: "BloomFilter") -> "BloomFilter":
        """
        Merge another Bloom filter into this one.
        
        Both filters must have the same size and hash count.
        
        Args:
            other: Another BloomFilter to merge
        
        Returns:
            Self for chaining
        
        Raises:
            ValueError: If filters are incompatible
        """
        if self._size != other._size or self._hash_count != other._hash_count:
            raise ValueError("Cannot merge incompatible Bloom filters")
        
        self._bit_array |= other._bit_array
        self._item_count += other._item_count
        return self
    
    def to_bytes(self) -> bytes:
        """Serialize the filter to bytes."""
        return self._bit_array.to_bytes(
            (self._bit_array.bit_length() + 7) // 8,
            byteorder='big'
        )
    
    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        expected_items: int,
        false_positive_rate: float
    ) -> "BloomFilter":
        """
        Deserialize a filter from bytes.
        
        Args:
            data: Serialized filter data
            expected_items: Original expected_items parameter
            false_positive_rate: Original false_positive_rate parameter
        
        Returns:
            Reconstructed BloomFilter
        """
        filter = cls(expected_items, false_positive_rate)
        filter._bit_array = int.from_bytes(data, byteorder='big')
        return filter
    
    def __len__(self) -> int:
        """Return item count."""
        return self._item_count
    
    def __repr__(self) -> str:
        return (
            f"BloomFilter(items={self._item_count}, "
            f"size={self.size_kb:.2f}KB, "
            f"fill={self.fill_ratio:.1%}, "
            f"est_fp_rate={self.estimated_false_positive_rate():.4f})"
        )


class URLDeduplicator:
    """
    Specialized Bloom filter for URL deduplication.
    
    Provides URL-specific normalization and convenient interface
    for article URL deduplication.
    """
    
    def __init__(
        self,
        expected_urls: int = 500_000,
        false_positive_rate: float = 0.001
    ) -> None:
        """
        Initialize URL deduplicator.
        
        Args:
            expected_urls: Expected number of URLs to track
            false_positive_rate: Acceptable false positive rate
        """
        self._filter = BloomFilter(expected_urls, false_positive_rate)
        self._normalize_urls = True
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent deduplication."""
        # Remove trailing slashes
        url = url.rstrip('/')
        
        # Remove common tracking parameters
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        
        parsed = urlparse(url)
        
        # Remove tracking query params
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
            'utm_content', 'ref', 'source', 'fbclid', 'gclid'
        }
        
        if parsed.query:
            params = parse_qs(parsed.query)
            filtered_params = {
                k: v for k, v in params.items()
                if k.lower() not in tracking_params
            }
            new_query = urlencode(filtered_params, doseq=True)
            parsed = parsed._replace(query=new_query)
        
        # Remove fragment
        parsed = parsed._replace(fragment='')
        
        return urlunparse(parsed).lower()
    
    def add(self, url: str) -> None:
        """Add a URL to the deduplicator."""
        normalized = self._normalize_url(url) if self._normalize_urls else url
        self._filter.add(normalized)
    
    def is_duplicate(self, url: str) -> bool:
        """Check if URL is a duplicate."""
        normalized = self._normalize_url(url) if self._normalize_urls else url
        return normalized in self._filter
    
    def is_new(self, url: str) -> bool:
        """Check if URL is new (not a duplicate)."""
        return not self.is_duplicate(url)
    
    def add_if_new(self, url: str) -> bool:
        """
        Add URL only if it's new.
        
        Args:
            url: URL to add
        
        Returns:
            True if URL was new and added, False if duplicate
        """
        if self.is_new(url):
            self.add(url)
            return True
        return False
    
    @property
    def count(self) -> int:
        """Get number of URLs tracked."""
        return len(self._filter)
    
    @property
    def stats(self) -> dict:
        """Get deduplicator statistics."""
        return {
            "url_count": self.count,
            "size_kb": self._filter.size_kb,
            "fill_ratio": self._filter.fill_ratio,
            "estimated_fp_rate": self._filter.estimated_false_positive_rate(),
        }
    
    def __contains__(self, url: str) -> bool:
        return self.is_duplicate(url)
    
    def __len__(self) -> int:
        return self.count
