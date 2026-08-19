"""
Unit Tests for FetchPolicy and RetryClassifier.
Location: tests/test_fetch_policy.py
"""

import socket
import unittest

from src.network.fetch_policy import FetchPolicy
from src.network.retry_classifier import RetryCategory, RetryClassifier
from src.security.ssrf_guard import PayloadSizeLimitExceeded, SSRFSecurityError


class TestFetchPolicy(unittest.TestCase):
    """Test cases for FetchPolicy configuration."""

    def test_default_policy(self):
        policy = FetchPolicy()
        self.assertEqual(policy.connect_timeout, 5.0)
        self.assertEqual(policy.max_redirects, 5)
        self.assertTrue(policy.respect_robots_txt)
        self.assertTrue(policy.honor_retry_after)

    def test_conditional_headers_generation(self):
        policy = FetchPolicy()
        headers = policy.with_conditional_headers(etag='"12345"', last_modified="Wed, 21 Oct 2025 07:28:00 GMT")
        self.assertEqual(headers["If-None-Match"], '"12345"')
        self.assertEqual(headers["If-Modified-Since"], "Wed, 21 Oct 2025 07:28:00 GMT")
        self.assertIn("TechNewsScrapper", headers["User-Agent"])


class TestRetryClassifier(unittest.TestCase):
    """Test cases for RetryClassifier."""

    def test_classify_200_ok(self):
        cat, delay = RetryClassifier.classify_status_code(200)
        self.assertEqual(cat, RetryCategory.SUCCESS)
        self.assertEqual(delay, 0.0)

    def test_classify_429_rate_limited_with_retry_after(self):
        cat, delay = RetryClassifier.classify_status_code(429, headers={"Retry-After": "30"})
        self.assertEqual(cat, RetryCategory.RATE_LIMITED)
        self.assertEqual(delay, 30.0)

    def test_classify_503_service_unavailable(self):
        cat, delay = RetryClassifier.classify_status_code(503)
        self.assertEqual(cat, RetryCategory.RETRYABLE)
        self.assertEqual(delay, 5.0)

    def test_classify_404_not_found(self):
        cat, delay = RetryClassifier.classify_status_code(404)
        self.assertEqual(cat, RetryCategory.NON_RETRYABLE)
        self.assertEqual(delay, 0.0)

    def test_classify_ssrf_exception(self):
        exc = SSRFSecurityError("Blocked IP")
        cat, delay = RetryClassifier.classify_exception(exc)
        self.assertEqual(cat, RetryCategory.SECURITY_REJECTED)
        self.assertEqual(delay, 0.0)

    def test_classify_payload_limit_exception(self):
        exc = PayloadSizeLimitExceeded("Decompression bomb")
        cat, delay = RetryClassifier.classify_exception(exc)
        self.assertEqual(cat, RetryCategory.POISON_PAYLOAD)
        self.assertEqual(delay, 0.0)

    def test_classify_timeout_exception(self):
        exc = TimeoutError("Connection timed out")
        cat, delay = RetryClassifier.classify_exception(exc)
        self.assertEqual(cat, RetryCategory.RETRYABLE)
        self.assertEqual(delay, 3.0)
