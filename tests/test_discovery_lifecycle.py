"""
Unit Tests for Source Discovery Lifecycle FSM.
Location: tests/test_discovery_lifecycle.py
"""

import unittest

from src.discovery.lifecycle import (
    DiscoveredSourceRecord,
    DiscoveryLifecycleManager,
    DiscoveryState,
    InvalidDiscoveryTransitionError,
)


class TestDiscoveryLifecycleManager(unittest.TestCase):
    """Test cases for DiscoveryLifecycleManager."""

    def setUp(self):
        self.mgr = DiscoveryLifecycleManager()

    def test_happy_path_promotion(self):
        url = "https://techblog.example.com/rss"
        rec = self.mgr.register_discovered(url, discovery_method="google_api")
        self.assertEqual(rec.state, DiscoveryState.DISCOVERED)

        rec = self.mgr.transition(url, DiscoveryState.VETTING)
        self.assertEqual(rec.state, DiscoveryState.VETTING)

        rec = self.mgr.transition(url, DiscoveryState.QUARANTINED)
        self.assertEqual(rec.state, DiscoveryState.QUARANTINED)

        rec = self.mgr.transition(url, DiscoveryState.PROMOTED, test_passed=True)
        self.assertEqual(rec.state, DiscoveryState.PROMOTED)
        self.assertEqual(rec.test_runs_passed, 1)

    def test_illegal_transition_raises(self):
        url = "https://untested.example.com"
        self.mgr.register_discovered(url)

        # Cannot jump from DISCOVERED directly to PROMOTED
        with self.assertRaises(InvalidDiscoveryTransitionError):
            self.mgr.transition(url, DiscoveryState.PROMOTED)

    def test_permanent_rejection_blacklists_url(self):
        malicious_url = "http://malware-feed.example.com"
        self.mgr.register_discovered(malicious_url)
        self.mgr.transition(malicious_url, DiscoveryState.REJECTED_PERMANENT, reason="SSRF Attempt")

        self.assertTrue(self.mgr.is_permanently_rejected(malicious_url))

        # Attempting to re-register should raise
        with self.assertRaises(InvalidDiscoveryTransitionError):
            self.mgr.register_discovered(malicious_url)

    def test_transient_retry_later_does_not_blacklist(self):
        flaky_url = "https://flaky.example.com/feed"
        self.mgr.register_discovered(flaky_url)
        self.mgr.transition(flaky_url, DiscoveryState.VETTING)
        rec = self.mgr.transition(flaky_url, DiscoveryState.RETRY_LATER, reason="HTTP 504 Gateway Timeout")

        self.assertEqual(rec.state, DiscoveryState.RETRY_LATER)
        self.assertIsNotNone(rec.next_retry_at)
        self.assertFalse(self.mgr.is_permanently_rejected(flaky_url))

        # Can transition back to VETTING when retry timer arrives
        rec2 = self.mgr.transition(flaky_url, DiscoveryState.VETTING)
        self.assertEqual(rec2.state, DiscoveryState.VETTING)
