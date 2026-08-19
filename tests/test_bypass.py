"""
Unit tests for the bypass module.

Tests anti-bot bypass, paywall bypass, stealth configuration,
and proxy management functionality.
"""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestStealthConfig(unittest.TestCase):
    """Test cases for StealthConfig class."""
    
    def test_import_stealth(self):
        """Test that stealth module imports correctly."""
        from src.bypass.stealth import StealthConfig, get_random_user_agent, get_stealth_headers
        
        self.assertIsNotNone(StealthConfig)
        self.assertIsNotNone(get_random_user_agent)
        self.assertIsNotNone(get_stealth_headers)
    
    def test_random_user_agent(self):
        """Test User-Agent rotation."""
        from src.bypass.stealth import get_random_user_agent, USER_AGENTS
        
        ua = get_random_user_agent()
        self.assertIsInstance(ua, str)
        self.assertIn(ua, USER_AGENTS)
        
        # Test randomness - get multiple and check for variation
        agents = [get_random_user_agent() for _ in range(20)]
        unique_agents = set(agents)
        # Should have at least some variation
        self.assertGreater(len(unique_agents), 1)
    
    def test_stealth_headers(self):
        """Test stealth header generation."""
        from src.bypass.stealth import get_stealth_headers
        
        headers = get_stealth_headers()
        
        self.assertIn("User-Agent", headers)
        self.assertIn("Accept", headers)
        self.assertIn("Accept-Language", headers)
        self.assertIn("Sec-Fetch-Dest", headers)
    
    def test_stealth_headers_with_referer(self):
        """Test stealth headers with custom referer."""
        from src.bypass.stealth import get_stealth_headers
        
        referer = "https://www.google.com/"
        headers = get_stealth_headers(referer=referer)
        
        self.assertEqual(headers["Referer"], referer)
    
    def test_stealth_config_initialization(self):
        """Test StealthConfig initialization."""
        from src.bypass.stealth import StealthConfig
        
        config = StealthConfig()
        
        self.assertIsInstance(config.user_agent, str)
        self.assertIsInstance(config.viewport, dict)
        self.assertIn("width", config.viewport)
        self.assertIn("height", config.viewport)
        self.assertIsInstance(config.timezone, str)
    
    def test_stealth_config_playwright_args(self):
        """Test Playwright context arguments generation."""
        from src.bypass.stealth import StealthConfig
        
        config = StealthConfig()
        args = config.get_playwright_context_args()
        
        self.assertIn("user_agent", args)
        self.assertIn("viewport", args)
        self.assertIn("locale", args)
    
    def test_stealth_config_google_referer(self):
        """Test Google referer configuration."""
        from src.bypass.stealth import StealthConfig
        
        config = StealthConfig.for_google_referer()
        
        self.assertIn("Referer", config.headers)
        self.assertIn("google", config.headers["Referer"].lower())


class TestAntiBotBypass(unittest.TestCase):
    """Test cases for AntiBotBypass class."""
    
    def test_import_anti_bot(self):
        """Test that anti_bot module imports correctly."""
        from src.bypass.anti_bot import AntiBotBypass, ProtectionType
        
        self.assertIsNotNone(AntiBotBypass)
        self.assertIsNotNone(ProtectionType)
    
    def test_protection_detection_cloudflare(self):
        """Test Cloudflare detection."""
        from src.bypass.anti_bot import AntiBotBypass, ProtectionType
        
        bypass = AntiBotBypass()
        
        # Test Cloudflare patterns
        cf_html = """
        <html>
        <body>
        <div>Checking your browser before accessing the site.</div>
        <div class="cf-browser-verification">Please wait...</div>
        </body>
        </html>
        """
        
        protection = bypass.detect_protection(cf_html, {})
        self.assertEqual(protection, ProtectionType.CLOUDFLARE_CHALLENGE)
    
    def test_protection_detection_none(self):
        """Test no protection detection."""
        from src.bypass.anti_bot import AntiBotBypass, ProtectionType
        
        bypass = AntiBotBypass()
        
        normal_html = """
        <html>
        <body>
        <article>This is a normal article content.</article>
        </body>
        </html>
        """
        
        protection = bypass.detect_protection(normal_html, {})
        self.assertEqual(protection, ProtectionType.NONE)
    
    def test_is_blocked(self):
        """Test block detection."""
        from src.bypass.anti_bot import AntiBotBypass
        
        bypass = AntiBotBypass()
        
        # Empty content should be blocked
        self.assertTrue(bypass.is_blocked("", 200))
        
        # Short content should be blocked
        self.assertTrue(bypass.is_blocked("Error", 200))
        
        # 403 status should be blocked
        self.assertTrue(bypass.is_blocked("<html>Access Denied</html>", 403))


class TestPaywallBypass(unittest.TestCase):
    """Test cases for PaywallBypass class."""
    
    def test_import_paywall(self):
        """Test that paywall module imports correctly."""
        from src.bypass.paywall import PaywallBypass, PaywallMethod
        
        self.assertIsNotNone(PaywallBypass)
        self.assertIsNotNone(PaywallMethod)
    
    def test_paywall_detection_patterns(self):
        """Test paywall detection patterns."""
        from src.bypass.paywall import PaywallBypass
        
        bypass = PaywallBypass()
        
        paywall_html = """
        <html>
        <body>
        <div class="paywall">Subscribe to continue reading</div>
        <p>You've reached your free article limit.</p>
        </body>
        </html>
        """
        
        self.assertTrue(bypass.detect_paywall(paywall_html))
    
    def test_paywall_detection_no_paywall(self):
        """Test detection of non-paywalled content."""
        from src.bypass.paywall import PaywallBypass
        
        bypass = PaywallBypass()
        
        normal_html = """
        <html>
        <body>
        <article>
        This is a long article with plenty of content that you can read
        freely without any subscription or paywall limitations. The content
        continues here with more interesting information about technology.
        </article>
        </body>
        </html>
        """
        
        self.assertFalse(bypass.detect_paywall(normal_html))
    
    def test_auto_method_selection(self):
        """Test automatic bypass method selection."""
        from src.bypass.paywall import PaywallBypass, PaywallMethod
        
        bypass = PaywallBypass()
        
        # Known paywalled sites should get specific methods
        method = bypass.auto_select_method("https://www.nytimes.com/article/test")
        self.assertEqual(method, PaywallMethod.GOOGLE_CACHE)
        
        method = bypass.auto_select_method("https://medium.com/article/test")
        self.assertEqual(method, PaywallMethod.DOM_MANIPULATION)


class TestProxyManager(unittest.TestCase):
    """Test cases for ProxyManager class."""
    
    def test_import_proxy_manager(self):
        """Test that proxy_manager module imports correctly."""
        from src.bypass.proxy_manager import ProxyManager, ProxyProtocol
        
        self.assertIsNotNone(ProxyManager)
        self.assertIsNotNone(ProxyProtocol)
    
    def test_add_proxy(self):
        """Test adding proxies."""
        from src.bypass.proxy_manager import ProxyManager
        
        manager = ProxyManager()
        
        manager.add_proxy("http://proxy1:8080")
        manager.add_proxy("socks5://proxy2:1080")
        
        self.assertEqual(len(manager.proxies), 2)
    
    def test_get_next_proxy(self):
        """Test proxy rotation."""
        from src.bypass.proxy_manager import ProxyManager
        
        manager = ProxyManager(rotation_interval=5)
        
        manager.add_proxy("http://proxy1:8080")
        manager.add_proxy("http://proxy2:8080")
        
        proxy1 = manager.get_next_proxy()
        self.assertIsNotNone(proxy1)
        
        # Should be able to get proxies
        proxy2 = manager.get_next_proxy()
        self.assertIsNotNone(proxy2)
        
        # Both proxies should be valid proxy URLs
        self.assertIn("proxy", proxy1)
        self.assertIn("proxy", proxy2)
    
    def test_mark_failure(self):
        """Test proxy failure handling."""
        from src.bypass.proxy_manager import ProxyManager
        
        manager = ProxyManager(max_failures=2)
        
        manager.add_proxy("http://proxy1:8080")
        
        # Mark failures
        manager.mark_failure("http://proxy1:8080")
        manager.mark_failure("http://proxy1:8080")
        
        # Proxy should be marked unhealthy
        self.assertFalse(manager.proxies[0].is_healthy)
    
    def test_get_healthy_proxies(self):
        """Test getting healthy proxies."""
        from src.bypass.proxy_manager import ProxyManager
        
        manager = ProxyManager()
        
        manager.add_proxy("http://proxy1:8080")
        manager.add_proxy("http://proxy2:8080")
        
        healthy = manager.get_healthy_proxies()
        self.assertEqual(len(healthy), 2)
    
    def test_get_stats(self):
        """Test proxy statistics."""
        from src.bypass.proxy_manager import ProxyManager
        
        manager = ProxyManager()
        
        manager.add_proxy("http://proxy1:8080")
        manager.mark_success("http://proxy1:8080")
        
        stats = manager.get_stats()
        
        self.assertEqual(stats["total_proxies"], 1)
        self.assertEqual(stats["success_count"], 1)


class TestBypassModuleImport(unittest.TestCase):
    """Test that the main bypass module imports correctly."""
    
    def test_main_import(self):
        """Test main bypass module import."""
        from src.bypass import (
            AntiBotBypass,
            PaywallBypass,
            StealthConfig,
            ProxyManager,
            ProtectionType,
            PaywallMethod,
        )
        
        self.assertIsNotNone(AntiBotBypass)
        self.assertIsNotNone(PaywallBypass)
        self.assertIsNotNone(StealthConfig)
        self.assertIsNotNone(ProxyManager)
        self.assertIsNotNone(ProtectionType)
        self.assertIsNotNone(PaywallMethod)


if __name__ == '__main__':
    unittest.main()
