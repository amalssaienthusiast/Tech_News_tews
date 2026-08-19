import logging
import re
from typing import Set, List
from threading import Lock

logger = logging.getLogger(__name__)


class FastDeduplicator:
    """Fast URL deduplication using thread-safe set."""

    def __init__(self, max_size: int = 100000):
        self._seen_urls: Set[str] = set()
        self._lock = Lock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._max_size = max_size

    def check(self, url: str) -> bool:
        """Check if URL is in seen set."""
        with self._lock:
            return url in self._seen_urls

    def is_duplicate(self, url: str) -> bool:
        """Check if URL is a duplicate (thread-safe)."""
        with self._lock:
            if url in self._seen_urls:
                self._cache_hits += 1
                return True
            self._cache_misses += 1
            return False

    def add(self, url: str) -> bool:
        """Add URL to seen set (returns True if already existed)."""
        with self._lock:
            if url in self._seen_urls:
                return True
            self._seen_urls.add(url)
            if len(self._seen_urls) > self._max_size:
                oldest = next(iter(self._seen_urls))
                self._seen_urls.remove(oldest)
            return False

    def add_batch(self, urls: list[str]) -> int:
        new_count = 0
        for url in urls:
            if not self.add(url):
                new_count += 1
        return new_count

    def reset(self) -> None:
        with self._lock:
            self._seen_urls.clear()
            self._cache_hits = 0
            self._cache_misses = 0

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_seen": len(self._seen_urls),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "hit_rate": (
                    self._cache_hits / (self._cache_hits + self._cache_misses)
                    if (self._cache_hits + self._cache_misses) > 0
                    else 0
                ),
                "cache_size": self._max_size,
            }


class TitleDeduplicator:
    """Fast title deduplication using word token Jaccard similarity."""

    def __init__(self, threshold: float = 0.85, max_size: int = 10000):
        self.threshold = threshold
        self._max_size = max_size
        self._titles: List[str] = []
        self._lock = Lock()

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenize text into a set of lowercase words."""
        return set(re.findall(r'\b\w+\b', text.lower()))

    def is_duplicate(self, title: str) -> bool:
        if not title:
            return False

        title_tokens = self._tokenize(title)
        if not title_tokens:
            return False

        with self._lock:
            for existing_title in self._titles:
                existing_tokens = self._tokenize(existing_title)
                if not existing_tokens:
                    continue

                intersection = len(title_tokens.intersection(existing_tokens))
                union = len(title_tokens.union(existing_tokens))

                if union > 0:
                    similarity = intersection / union
                    if similarity >= self.threshold:
                        return True

            self._titles.append(title)
            if len(self._titles) > self._max_size:
                self._titles.pop(0)

        return False

    def add(self, title: str) -> None:
        if not title:
            return
        with self._lock:
            if title not in self._titles:
                self._titles.append(title)
                if len(self._titles) > self._max_size:
                    self._titles.pop(0)

    def reset(self) -> None:
        """Clear all seen titles."""
        with self._lock:
            self._titles.clear()
