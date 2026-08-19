"""
Unit tests for Content Platform Bypass module.

Tests universal bypass functionality for Medium, Substack, Ghost, and other
content delivery platforms.
"""

import asyncio
import unittest
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestContentPlatformDetection(unittest.TestCase):
    """Test platform detection logic."""
    
    def test_import_module(self):
        """Test that the module imports correctly."""
        from src.bypass.content_platform_bypass import (
            ContentPlatformBypass,
            ContentPlatform,
            PlatformBypassResult,
        )
        
        self.assertIsNotNone(ContentPlatformBypass)
        self.assertIsNotNone(ContentPlatform)
        self.assertIsNotNone(PlatformBypassResult)
    
    def test_detect_medium_domain(self):
        """Test detection of Medium.com URLs."""
        from src.bypass.content_platform_bypass import (
            ContentPlatformBypass,
            ContentPlatform,
        )
        
        bypass = ContentPlatformBypass()
        
        # Direct Medium URLs
        platform = bypass.detect_platform("https://medium.com/article/test")
        self.assertEqual(platform, ContentPlatform.MEDIUM)
        
        # Medium partner sites
        platform = bypass.detect_platform("https://towardsdatascience.com/article/test")
        self.assertEqual(platform, ContentPlatform.MEDIUM)
        
        platform = bypass.detect_platform("https://gitconnected.com/article/test")
        self.assertEqual(platform, ContentPlatform.MEDIUM)
        
        platform = bypass.detect_platform("https://betterprogramming.pub/article/test")
        self.assertEqual(platform, ContentPlatform.MEDIUM)
    
    def test_detect_substack_domain(self):
        """Test detection of Substack URLs."""
        from src.bypass.content_platform_bypass import (
            ContentPlatformBypass,
            ContentPlatform,
        )
        
        bypass = ContentPlatformBypass()
        
        platform = bypass.detect_platform("https://example.substack.com/p/article-title")
        self.assertEqual(platform, ContentPlatform.SUBSTACK)
    
    def test_detect_unknown_platform(self):
        """Test that unknown URLs return UNKNOWN platform."""
        from src.bypass.content_platform_bypass import (
            ContentPlatformBypass,
            ContentPlatform,
        )
        
        bypass = ContentPlatformBypass()
        
        platform = bypass.detect_platform("https://example.com/article")
        self.assertEqual(platform, ContentPlatform.UNKNOWN)


class TestPaywallDetection(unittest.TestCase):
    """Test paywall indicator detection."""
    
    def test_detect_member_only_paywall(self):
        """Test detection of member-only paywall text."""
        from src.bypass.content_platform_bypass import ContentPlatformBypass
        
        bypass = ContentPlatformBypass()
        
        html = """
        <html>
        <body>
        <p>This story is for premium members only.</p>
        </body>
        </html>
        """
        
        self.assertTrue(bypass.has_paywall(html))
    
    def test_detect_article_limit_paywall(self):
        """Test detection of article limit text."""
        from src.bypass.content_platform_bypass import ContentPlatformBypass
        
        bypass = ContentPlatformBypass()
        
        html = """
        <html>
        <body>
        <p>You have 2 free articles remaining this month.</p>
        </body>
        </html>
        """
        
        self.assertTrue(bypass.has_paywall(html))
    
    def test_no_paywall_detection(self):
        """Test that normal content is not flagged as paywalled."""
        from src.bypass.content_platform_bypass import ContentPlatformBypass
        
        bypass = ContentPlatformBypass()
        
        html = """
        <html>
        <body>
        <article>
        <h1>How to Code in Python</h1>
        <p>Python is a versatile programming language that is easy to learn.</p>
        </article>
        </body>
        </html>
        """
        
        self.assertFalse(bypass.has_paywall(html))


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting functionality."""
    
    def test_rate_limit_config(self):
        """Test rate limit configuration."""
        from src.bypass.content_platform_bypass import (
            ContentPlatformBypass,
            RateLimitConfig,
        )
        
        config = RateLimitConfig(
            max_requests_per_minute=5,
            max_requests_per_hour=30,
        )
        
        bypass = ContentPlatformBypass(rate_limit_config=config)
        
        self.assertEqual(bypass.rate_limit.max_requests_per_minute, 5)
        self.assertEqual(bypass.rate_limit.max_requests_per_hour, 30)


class TestPlatformSelectors(unittest.TestCase):
    """Test platform-specific selectors are defined."""
    
    def test_medium_selectors_exist(self):
        """Test that Medium selectors are defined."""
        from src.bypass.content_platform_bypass import (
            PLATFORM_SELECTORS,
            ContentPlatform,
        )
        
        medium_selectors = PLATFORM_SELECTORS.get(ContentPlatform.MEDIUM)
        
        self.assertIsNotNone(medium_selectors)
        self.assertIn("overlays", medium_selectors)
        self.assertIn("blur_targets", medium_selectors)
        self.assertIn("content_markers", medium_selectors)
        
        # Check for specific Medium selectors
        overlays = medium_selectors["overlays"]
        self.assertIn('div[data-testid="paywall-overlay"]', overlays)
        self.assertIn('.meteredContent', overlays)
    
    def test_substack_selectors_exist(self):
        """Test that Substack selectors are defined."""
        from src.bypass.content_platform_bypass import (
            PLATFORM_SELECTORS,
            ContentPlatform,
        )
        
        substack_selectors = PLATFORM_SELECTORS.get(ContentPlatform.SUBSTACK)
        
        self.assertIsNotNone(substack_selectors)
        self.assertIn("overlays", substack_selectors)


class TestPaywallPyIntegration(unittest.TestCase):
    """Test integration with paywall.py module."""
    
    def test_medium_in_known_sites(self):
        """Test that Medium is in KNOWN_PAYWALL_SITES with correct method."""
        from src.bypass.paywall import KNOWN_PAYWALL_SITES, PaywallMethod
        
        self.assertIn("medium.com", KNOWN_PAYWALL_SITES)
        self.assertEqual(
            KNOWN_PAYWALL_SITES["medium.com"],
            PaywallMethod.DOM_MANIPULATION
        )
    
    def test_medium_selectors_in_paywall_list(self):
        """Test that Medium selectors are in PAYWALL_SELECTORS."""
        from src.bypass.paywall import PAYWALL_SELECTORS
        
        self.assertIn('div[data-testid="paywall-overlay"]', PAYWALL_SELECTORS)
        self.assertIn('.meteredContent', PAYWALL_SELECTORS)
    
    def test_substack_in_known_sites(self):
        """Test that Substack is in KNOWN_PAYWALL_SITES."""
        from src.bypass.paywall import KNOWN_PAYWALL_SITES
        
        self.assertIn("substack.com", KNOWN_PAYWALL_SITES)


class TestModuleExports(unittest.TestCase):
    """Test module exports from __init__.py."""
    
    def test_content_platform_bypass_exported(self):
        """Test that ContentPlatformBypass is exported from src.bypass."""
        from src.bypass import (
            ContentPlatformBypass,
            ContentPlatform,
            PlatformBypassResult,
            bypass_content_platform,
        )
        
        self.assertIsNotNone(ContentPlatformBypass)
        self.assertIsNotNone(ContentPlatform)
        self.assertIsNotNone(PlatformBypassResult)
        self.assertIsNotNone(bypass_content_platform)


if __name__ == '__main__':
    unittest.main()
