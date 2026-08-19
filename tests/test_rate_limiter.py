"""
Unit tests for the Rate Limiter module.

Tests token bucket algorithm behavior, domain-specific limiting,
and async operations.
"""

import asyncio
import time
import unittest
from unittest.mock import patch

import sys
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.rate_limiter import RateLimiter, TokenBucket


class TestTokenBucket(unittest.TestCase):
    """Test cases for TokenBucket class."""
    
    def test_initialization(self):
        """Test bucket initializes with full capacity."""
        bucket = TokenBucket(capacity=10.0, refill_rate=2.0)
        self.assertEqual(bucket.available_tokens(), 10.0)
    
    def test_acquire_reduces_tokens(self):
        """Test that acquiring tokens reduces available count."""
        bucket = TokenBucket(capacity=10.0, refill_rate=2.0)
        
        result = bucket.acquire(timeout=0.1)
        
        self.assertTrue(result)
        self.assertAlmostEqual(bucket.available_tokens(), 9.0, delta=0.5)
    
    def test_try_acquire_immediate(self):
        """Test try_acquire returns immediately."""
        bucket = TokenBucket(capacity=2.0, refill_rate=1.0)
        
        # Should succeed twice
        self.assertTrue(bucket.try_acquire())
        self.assertTrue(bucket.try_acquire())
        
        # Should fail on third (no tokens left)
        self.assertFalse(bucket.try_acquire())
    
    def test_refill_over_time(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(capacity=10.0, refill_rate=10.0)  # 10 tokens/sec
        
        # Use all tokens
        for _ in range(10):
            bucket.try_acquire()
        
        self.assertLess(bucket.available_tokens(), 1.0)
        
        # Wait for refill
        time.sleep(0.2)  # Should add ~2 tokens
        
        tokens = bucket.available_tokens()
        self.assertGreater(tokens, 1.0)
    
    def test_capacity_limit(self):
        """Test tokens don't exceed capacity."""
        bucket = TokenBucket(capacity=5.0, refill_rate=100.0)
        
        time.sleep(0.1)  # Would add 10 tokens at this rate
        
        self.assertLessEqual(bucket.available_tokens(), 5.0)


class TestRateLimiter(unittest.TestCase):
    """Test cases for RateLimiter class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.limiter = RateLimiter(
            tokens_per_second=5.0,
            bucket_size=5
        )
    
    def test_initialization(self):
        """Test limiter initializes correctly."""
        self.assertEqual(self.limiter.tokens_per_second, 5.0)
        self.assertEqual(self.limiter.bucket_size, 5)
    
    def test_domain_extraction(self):
        """Test domain is extracted from URLs."""
        domain = self.limiter._get_domain("https://example.com/path/to/page")
        self.assertEqual(domain, "example.com")
    
    def test_separate_buckets_per_domain(self):
        """Test each domain gets its own bucket."""
        # Use tokens from domain A
        for _ in range(5):
            self.limiter.try_acquire("https://domain-a.com/page")
        
        # Domain B should still have full tokens
        self.assertTrue(self.limiter.try_acquire("https://domain-b.com/page"))
        
        # Domain A should be empty
        self.assertFalse(self.limiter.try_acquire("https://domain-a.com/page2"))
    
    def test_wait_blocks_until_available(self):
        """Test wait method blocks until token available."""
        # Use all tokens
        for _ in range(5):
            self.limiter.try_acquire("https://test.com/page")
        
        start = time.time()
        result = self.limiter.wait("https://test.com/page", timeout=1.0)
        elapsed = time.time() - start
        
        self.assertTrue(result)
        self.assertGreater(elapsed, 0.1)  # Should have waited
    
    def test_wait_timeout(self):
        """Test wait returns False on timeout."""
        limiter = RateLimiter(tokens_per_second=0.1, bucket_size=1)
        
        limiter.try_acquire("https://slow.com/page")
        
        result = limiter.wait("https://slow.com/page", timeout=0.1)
        
        self.assertFalse(result)
    
    def test_get_stats(self):
        """Test statistics retrieval."""
        self.limiter.try_acquire("https://stats-test.com/page")
        
        stats = self.limiter.get_stats()
        
        self.assertIn("stats-test.com", stats)
        self.assertIn("tokens", stats["stats-test.com"])
        self.assertIn("capacity", stats["stats-test.com"])
    
    def test_reset(self):
        """Test reset restores tokens to capacity."""
        # Use some tokens
        for _ in range(3):
            self.limiter.try_acquire("https://reset-test.com/page")
        
        self.limiter.reset("reset-test.com")
        
        stats = self.limiter.get_stats()
        self.assertEqual(stats["reset-test.com"]["tokens"], 5.0)


class TestRateLimiterAsync(unittest.TestCase):
    """Test cases for async rate limiter operations."""
    
    def test_async_wait(self):
        """Test async wait method."""
        limiter = RateLimiter(tokens_per_second=5.0, bucket_size=5)
        
        async def test():
            result = await limiter.wait_async("https://async-test.com/page")
            return result
        
        result = asyncio.run(test())
        self.assertTrue(result)
    
    def test_async_wait_timeout(self):
        """Test async wait with timeout."""
        limiter = RateLimiter(tokens_per_second=0.1, bucket_size=1)
        
        # Use the only token
        limiter.try_acquire("https://async-timeout.com/page")
        
        async def test():
            result = await limiter.wait_async(
                "https://async-timeout.com/page", 
                timeout=0.1
            )
            return result
        
        result = asyncio.run(test())
        self.assertFalse(result)


class TestGlobalRateLimiter(unittest.TestCase):
    """Test cases for global rate limiter with cross-domain limiting."""
    
    def test_global_limit(self):
        """Test global rate limit across all domains."""
        limiter = RateLimiter(
            tokens_per_second=10.0,
            bucket_size=2,  # Small bucket
            global_limit=1.0  # Only 1 request/sec globally
        )
        
        # First two should succeed (initial bucket capacity)
        self.assertTrue(limiter.try_acquire("https://domain1.com/page"))
        self.assertTrue(limiter.try_acquire("https://domain2.com/page"))
        
        # Third should fail due to global limit exhaustion
        result = limiter.try_acquire("https://domain3.com/page")
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
