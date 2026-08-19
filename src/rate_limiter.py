"""
Token bucket rate limiter for controlling HTTP request rates.

This module implements a production-ready token bucket algorithm for
rate limiting, with support for domain-specific limits and async/await
patterns. Used to prevent overwhelming target servers and avoid
IP bans during web scraping.

Design Pattern: Token Bucket Algorithm
- Tokens are added to a bucket at a fixed rate
- Each request consumes one token
- If no tokens available, request must wait
- Bucket has max capacity to allow bursting
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """
    Token bucket for a single domain.
    
    Implements the token bucket algorithm with thread-safe token management.
    Tokens refill over time up to the maximum capacity.
    
    Attributes:
        capacity: Maximum number of tokens the bucket can hold.
        refill_rate: Tokens added per second.
        tokens: Current number of available tokens.
        last_refill: Timestamp of last token refill.
        lock: Threading lock for thread-safe access.
    """
    capacity: float
    refill_rate: float
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.time)
    lock: Lock = field(default_factory=Lock, repr=False)
    
    def __post_init__(self) -> None:
        """Initialize tokens to capacity after dataclass init."""
        self.tokens = self.capacity
    
    def _refill(self) -> None:
        """
        Refill tokens based on elapsed time.
        
        Calculates how many tokens should be added since last refill
        and adds them up to the bucket capacity.
        
        Note: Must be called while holding the lock.
        """
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Attempt to acquire a token from the bucket (blocking).
        
        Args:
            timeout: Maximum seconds to wait. None means wait forever.
        
        Returns:
            True if token was acquired, False if timeout elapsed.
        """
        deadline = None if timeout is None else time.time() + timeout
        
        while True:
            with self.lock:
                self._refill()
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
                
                # Calculate wait time until next token
                wait_time = (1.0 - self.tokens) / self.refill_rate
            
            # Check timeout
            if deadline is not None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                wait_time = min(wait_time, remaining)
            
            time.sleep(wait_time)
    
    async def acquire_async(self, timeout: Optional[float] = None) -> bool:
        """
        Asynchronously acquire a token from the bucket.
        
        Args:
            timeout: Maximum seconds to wait. None means wait forever.
        
        Returns:
            True if token was acquired, False if timeout elapsed.
        """
        deadline = None if timeout is None else time.time() + timeout
        
        while True:
            with self.lock:
                self._refill()
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
                
                # Calculate wait time until next token
                wait_time = (1.0 - self.tokens) / self.refill_rate
            
            # Check timeout
            if deadline is not None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                wait_time = min(wait_time, remaining)
            
            await asyncio.sleep(wait_time)
    
    def try_acquire(self) -> bool:
        """
        Try to acquire a token without waiting.
        
        Returns:
            True if token was acquired, False if none available.
        """
        with self.lock:
            self._refill()
            
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            
            return False
    
    def available_tokens(self) -> float:
        """
        Get the current number of available tokens.
        
        Returns:
            Number of tokens available for acquisition.
        """
        with self.lock:
            self._refill()
            return self.tokens


class RateLimiter:
    """
    Domain-aware rate limiter using token buckets.
    
    Manages rate limiting across multiple domains, creating separate
    token buckets for each domain to ensure fair distribution of
    requests and compliance with per-site rate limits.
    
    Example:
        limiter = RateLimiter(tokens_per_second=2.0, bucket_size=10)
        
        # Synchronous usage
        limiter.wait("https://example.com/page1")
        response = requests.get("https://example.com/page1")
        
        # Async usage
        await limiter.wait_async("https://example.com/page2")
        async with aiohttp.ClientSession() as session:
            response = await session.get("https://example.com/page2")
    
    Attributes:
        tokens_per_second: Rate at which tokens refill.
        bucket_size: Maximum tokens per bucket (burst capacity).
        buckets: Dictionary mapping domains to their token buckets.
        global_bucket: Optional global rate limit across all domains.
    """
    
    def __init__(
        self,
        tokens_per_second: float = 2.0,
        bucket_size: int = 10,
        global_limit: Optional[float] = None
    ) -> None:
        """
        Initialize the rate limiter.
        
        Args:
            tokens_per_second: Tokens added per second per domain.
            bucket_size: Maximum tokens each bucket can hold.
            global_limit: Optional global rate limit (tokens/sec) across
                         all domains. If None, no global limit is applied.
        """
        self.tokens_per_second = tokens_per_second
        self.bucket_size = bucket_size
        self._buckets: Dict[str, TokenBucket] = {}
        self._buckets_lock = Lock()
        
        # Optional global rate limit
        self._global_bucket: Optional[TokenBucket] = None
        if global_limit is not None:
            self._global_bucket = TokenBucket(
                capacity=float(bucket_size),
                refill_rate=global_limit
            )
        
        logger.info(
            f"RateLimiter initialized: {tokens_per_second} tokens/sec, "
            f"bucket size {bucket_size}"
        )
    
    def _get_domain(self, url: str) -> str:
        """
        Extract domain from URL.
        
        Args:
            url: Full URL string.
        
        Returns:
            Domain name (netloc) from the URL.
        """
        parsed = urlparse(url)
        return parsed.netloc or url
    
    def _get_bucket(self, domain: str) -> TokenBucket:
        """
        Get or create a token bucket for a domain.
        
        Args:
            domain: Domain name to get bucket for.
        
        Returns:
            TokenBucket instance for the domain.
        """
        with self._buckets_lock:
            if domain not in self._buckets:
                self._buckets[domain] = TokenBucket(
                    capacity=float(self.bucket_size),
                    refill_rate=self.tokens_per_second
                )
                logger.debug(f"Created bucket for domain: {domain}")
            return self._buckets[domain]
    
    def wait(self, url: str, timeout: Optional[float] = None) -> bool:
        """
        Wait until rate limit allows a request to the URL (blocking).
        
        Args:
            url: Target URL for the request.
            timeout: Maximum seconds to wait.
        
        Returns:
            True if rate limit acquired, False if timeout.
        """
        domain = self._get_domain(url)
        bucket = self._get_bucket(domain)
        
        # Acquire domain-specific token
        if not bucket.acquire(timeout):
            logger.warning(f"Rate limit timeout for {domain}")
            return False
        
        # Acquire global token if configured
        if self._global_bucket is not None:
            if not self._global_bucket.acquire(timeout):
                logger.warning("Global rate limit timeout")
                return False
        
        return True
    
    async def wait_async(
        self, 
        url: str, 
        timeout: Optional[float] = None
    ) -> bool:
        """
        Asynchronously wait until rate limit allows a request.
        
        Args:
            url: Target URL for the request.
            timeout: Maximum seconds to wait.
        
        Returns:
            True if rate limit acquired, False if timeout.
        """
        domain = self._get_domain(url)
        bucket = self._get_bucket(domain)
        
        # Acquire domain-specific token
        if not await bucket.acquire_async(timeout):
            logger.warning(f"Rate limit timeout for {domain}")
            return False
        
        # Acquire global token if configured
        if self._global_bucket is not None:
            if not await self._global_bucket.acquire_async(timeout):
                logger.warning("Global rate limit timeout")
                return False
        
        return True
    
    def try_acquire(self, url: str) -> bool:
        """
        Try to acquire rate limit without waiting.
        
        Args:
            url: Target URL for the request.
        
        Returns:
            True if acquired, False if rate limited.
        """
        domain = self._get_domain(url)
        bucket = self._get_bucket(domain)
        
        if not bucket.try_acquire():
            return False
        
        if self._global_bucket is not None:
            if not self._global_bucket.try_acquire():
                # Return the domain token since we couldn't get global
                with bucket.lock:
                    bucket.tokens = min(bucket.capacity, bucket.tokens + 1)
                return False
        
        return True
    
    def get_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get statistics about all rate limit buckets.
        
        Returns:
            Dictionary mapping domains to their bucket stats.
        """
        stats = {}
        with self._buckets_lock:
            for domain, bucket in self._buckets.items():
                stats[domain] = {
                    "tokens": bucket.available_tokens(),
                    "capacity": bucket.capacity,
                    "rate": bucket.refill_rate
                }
        
        if self._global_bucket is not None:
            stats["__global__"] = {
                "tokens": self._global_bucket.available_tokens(),
                "capacity": self._global_bucket.capacity,
                "rate": self._global_bucket.refill_rate
            }
        
        return stats
    
    def reset(self, domain: Optional[str] = None) -> None:
        """
        Reset rate limit buckets to full capacity.
        
        Args:
            domain: Specific domain to reset. If None, resets all.
        """
        with self._buckets_lock:
            if domain is not None:
                if domain in self._buckets:
                    bucket = self._buckets[domain]
                    with bucket.lock:
                        bucket.tokens = bucket.capacity
                        bucket.last_refill = time.time()
            else:
                for bucket in self._buckets.values():
                    with bucket.lock:
                        bucket.tokens = bucket.capacity
                        bucket.last_refill = time.time()
        
        if self._global_bucket is not None:
            with self._global_bucket.lock:
                self._global_bucket.tokens = self._global_bucket.capacity
                self._global_bucket.last_refill = time.time()


# Global rate limiter instance (configured on import)
_default_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """
    Get the global rate limiter instance.
    
    Creates a default instance if none exists.
    
    Returns:
        Global RateLimiter instance.
    """
    global _default_limiter
    if _default_limiter is None:
        # Import here to avoid circular imports
        from config.settings import (
            RATE_LIMIT_TOKENS_PER_SECOND,
            RATE_LIMIT_BUCKET_SIZE
        )
        _default_limiter = RateLimiter(
            tokens_per_second=RATE_LIMIT_TOKENS_PER_SECOND,
            bucket_size=RATE_LIMIT_BUCKET_SIZE
        )
    return _default_limiter


def configure_rate_limiter(
    tokens_per_second: float = 2.0,
    bucket_size: int = 10,
    global_limit: Optional[float] = None
) -> RateLimiter:
    """
    Configure and return the global rate limiter.
    
    Args:
        tokens_per_second: Tokens added per second per domain.
        bucket_size: Maximum tokens each bucket can hold.
        global_limit: Optional global rate limit.
    
    Returns:
        Configured global RateLimiter instance.
    """
    global _default_limiter
    _default_limiter = RateLimiter(
        tokens_per_second=tokens_per_second,
        bucket_size=bucket_size,
        global_limit=global_limit
    )
    return _default_limiter
