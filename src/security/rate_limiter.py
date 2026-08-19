"""
Token Bucket Rate Limiter and Protocol.
Location: src/security/rate_limiter.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import math
import time
from typing import Dict, Optional, Protocol, Tuple, runtime_checkable

from .models import RateLimitResult, Role

logger = logging.getLogger(__name__)


@dataclass
class _BucketState:
    tokens: float
    last_refill_timestamp: float
    capacity: float
    refill_rate_per_sec: float
    last_access_timestamp: float


# Default (Capacity, RefillRatePerSec) per role
DEFAULT_ROLE_QUOTAS: Dict[Role, Tuple[float, float]] = {
    Role.ADMIN: (200.0, 16.67),       # 1000/min, burst 200
    Role.READ_WRITE: (60.0, 5.0),     # 300/min, burst 60
    Role.READ_ONLY: (30.0, 2.0),      # 120/min, burst 30
    Role.ANONYMOUS: (10.0, 0.5),      # 30/min, burst 10
}


@runtime_checkable
class RateLimiterProtocol(Protocol):
    """Abstract rate limiter interface."""

    async def check_rate_limit(
        self,
        key: str,
        role: Role = Role.ANONYMOUS,
        cost: float = 1.0,
    ) -> RateLimitResult:
        """Check and consume rate limit tokens for a client key."""
        ...


class LocalTokenBucketLimiter(RateLimiterProtocol):
    """
    In-memory asynchronous token bucket rate limiter.
    
    Provides thread/async-safe rate limiting with role-based quotas,
    burst capacity, and idle bucket eviction.
    """

    def __init__(
        self,
        role_quotas: Optional[Dict[Role, Tuple[float, float]]] = None,
        stale_threshold_seconds: float = 3600.0,
    ) -> None:
        self.role_quotas = role_quotas or DEFAULT_ROLE_QUOTAS
        self.stale_threshold_seconds = stale_threshold_seconds
        self._buckets: Dict[str, _BucketState] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self,
        key: str,
        role: Role = Role.ANONYMOUS,
        cost: float = 1.0,
    ) -> RateLimitResult:
        """
        Evaluate rate limit for the given key and role.
        """
        async with self._lock:
            now = time.monotonic()
            capacity, refill_rate = self.role_quotas.get(role, self.role_quotas[Role.ANONYMOUS])

            # Periodic stale eviction if bucket count grows large
            if len(self._buckets) > 5000:
                self._evict_stale_buckets(now)

            if key not in self._buckets:
                self._buckets[key] = _BucketState(
                    tokens=capacity,
                    last_refill_timestamp=now,
                    capacity=capacity,
                    refill_rate_per_sec=refill_rate,
                    last_access_timestamp=now,
                )

            bucket = self._buckets[key]
            bucket.last_access_timestamp = now

            # Calculate token replenishment
            elapsed = now - bucket.last_refill_timestamp
            if elapsed > 0:
                bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate_per_sec)
                bucket.last_refill_timestamp = now

            limit_per_min = int(bucket.refill_rate_per_sec * 60)

            # Check if sufficient tokens exist
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                remaining = int(math.floor(bucket.tokens))
                reset_secs = (bucket.capacity - bucket.tokens) / bucket.refill_rate_per_sec if bucket.refill_rate_per_sec > 0 else 0.0
                return RateLimitResult(
                    allowed=True,
                    limit=limit_per_min,
                    remaining=remaining,
                    reset_seconds=round(reset_secs, 2),
                    retry_after=None,
                )
            else:
                # Throttled
                missing_tokens = cost - bucket.tokens
                retry_after_sec = max(1, int(math.ceil(missing_tokens / bucket.refill_rate_per_sec)))
                reset_secs = bucket.capacity / bucket.refill_rate_per_sec if bucket.refill_rate_per_sec > 0 else 0.0
                return RateLimitResult(
                    allowed=False,
                    limit=limit_per_min,
                    remaining=0,
                    reset_seconds=round(reset_secs, 2),
                    retry_after=retry_after_sec,
                )

    def _evict_stale_buckets(self, now: float) -> None:
        """Prune buckets that have not been accessed within the stale threshold."""
        stale_keys = [
            k for k, v in self._buckets.items()
            if (now - v.last_access_timestamp) > self.stale_threshold_seconds
        ]
        for k in stale_keys:
            del self._buckets[k]
