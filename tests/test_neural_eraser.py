"""
Unit tests for the Neural DOM Eraser paywall bypass logic.

These tests verify the JavaScript injection and DOM manipulation
logic used to remove paywall overlays.
"""

import unittest
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestNeuralDOMEraserScript(unittest.TestCase):
    """Test cases for the Neural DOM Eraser JavaScript logic."""
    
    def test_eraser_script_exists_in_browser_engine(self):
        """Test that the _smart_paywall_bypass method is defined."""
        from src.bypass.browser_engine import StealthBrowser
        
        browser = StealthBrowser.__new__(StealthBrowser)
        self.assertTrue(hasattr(browser, '_smart_paywall_bypass'))
        self.assertTrue(callable(getattr(browser, '_smart_paywall_bypass', None)))
    
    def test_eraser_script_contains_keywords(self):
        """Test that the eraser script contains expected semantic keywords."""
        from src.bypass.browser_engine import StealthBrowser
        import inspect
        
        # Get the source code of the method
        source = inspect.getsource(StealthBrowser._smart_paywall_bypass)
        
        # Check for expected keywords in the JS script
        expected_keywords = ['subscribe', 'premium', 'unlock', 'paywall', 'z-index']
        for kw in expected_keywords:
            self.assertIn(kw.lower(), source.lower(), f"Keyword '{kw}' not found in eraser script.")
    
    def test_eraser_script_has_coverage_logic(self):
        """Test that the eraser script has viewport coverage calculation."""
        from src.bypass.browser_engine import StealthBrowser
        import inspect
        
        source = inspect.getsource(StealthBrowser._smart_paywall_bypass)
        
        self.assertIn('getBoundingClientRect', source)
        self.assertIn('innerWidth', source)
        self.assertIn('innerHeight', source)
    
    def test_eraser_script_has_scrubbing_logic(self):
        """Test that the eraser script scrubs blur, user-select, etc."""
        from src.bypass.browser_engine import StealthBrowser
        import inspect
        
        source = inspect.getsource(StealthBrowser._smart_paywall_bypass)
        
        self.assertIn('blur', source.lower())
        self.assertIn('userSelect', source)
        self.assertIn('pointerEvents', source)
        self.assertIn('overflow', source)


class TestPaywallStaticEraser(unittest.TestCase):
    """Test semantic eraser fallback in paywall.py (non-Playwright)."""

    def test_dom_manipulation_bypass_exists(self):
        """Test that dom_manipulation_bypass method exists."""
        from src.bypass.paywall import PaywallBypass
        
        bypass = PaywallBypass.__new__(PaywallBypass)
        self.assertTrue(hasattr(bypass, 'dom_manipulation_bypass'))

    def test_static_eraser_removes_overlay_divs(self):
        """Test that static eraser removes divs with paywall keywords."""
        from src.bypass.paywall import PaywallBypass
        from bs4 import BeautifulSoup
        
        bypass = PaywallBypass()
        
        # Mock HTML with a paywall overlay
        html = """
        <html>
        <body>
        <article>This is the main article content that should remain.</article>
        <div class="paywall" style="z-index: 9999; position: fixed;">
            Subscribe to continue reading. Unlock premium access now.
        </div>
        </body>
        </html>
        """
        
        # Simulate the logic from dom_manipulation_bypass
        soup = BeautifulSoup(html, "html.parser")
        for selector in bypass.selectors:
            for element in soup.select(selector):
                element.decompose()
        
        cleaned_html = str(soup)
        
        self.assertIn("main article content", cleaned_html)
        self.assertNotIn("Subscribe to continue", cleaned_html)


if __name__ == '__main__':
    unittest.main()
