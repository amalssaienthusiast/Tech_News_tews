#!/usr/bin/env python3
"""
Integration test for the full bypass → analysis pipeline.

Tests end-to-end flow from URL input through bypass to content analysis.
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestBypassToAnalysisPipeline(unittest.IsolatedAsyncioTestCase):
    """Integration tests for bypass → analysis pipeline."""
    
    async def test_content_platform_detection_to_bypass(self):
        """Test that content platforms are detected and bypass is attempted."""
        from src.bypass import ContentPlatformBypass, ContentPlatform
        
        bypass = ContentPlatformBypass()
        
        # Test Medium detection
        medium_urls = [
            "https://medium.com/article/test",
            "https://towardsdatascience.com/article/test",
            "https://betterprogramming.pub/article/test",
        ]
        
        for url in medium_urls:
            platform = bypass.detect_platform(url)
            self.assertEqual(platform, ContentPlatform.MEDIUM, f"Failed for {url}")
        
        # Test Substack detection
        substack_url = "https://example.substack.com/p/article"
        platform = bypass.detect_platform(substack_url)
        self.assertEqual(platform, ContentPlatform.SUBSTACK)
    
    async def test_deep_scraper_uses_content_platform_bypass(self):
        """Test that DeepScraper uses ContentPlatformBypass for known platforms."""
        from src.engine.deep_scraper import DeepScraper
        from src.bypass import ContentPlatform
        
        scraper = DeepScraper()
        
        # Verify content platform bypass is initialized
        self.assertIsNotNone(scraper._content_platform_bypass)
        
        # Verify it can detect platforms
        platform = scraper._content_platform_bypass.detect_platform(
            "https://medium.com/test"
        )
        self.assertEqual(platform, ContentPlatform.MEDIUM)
    
    async def test_content_platform_bypass_capabilities(self):
        """Test ContentPlatformBypass interface capabilities."""
        from src.bypass import ContentPlatformBypass
        
        bypass = ContentPlatformBypass()
        self.assertTrue(hasattr(bypass, 'detect_platform'))
        self.assertTrue(hasattr(bypass, 'bypass'))
    
    async def test_spa_content_extraction(self):
        """Test enhanced SPA content extraction from JSON-LD."""
        from src.bypass import ContentPlatformBypass, ContentPlatform
        
        bypass = ContentPlatformBypass()
        
        # Mock Medium HTML with JSON-LD - needs enough words to pass threshold
        long_article = " ".join(["word"] * 200)  # 200 words
        html = f'''
        <html>
        <head>
            <script type="application/ld+json">
            {{
                "@type": "Article",
                "description": "This is a test article about Python programming.",
                "articleBody": "Python is a versatile programming language. {long_article}"
            }}
            </script>
        </head>
        <body>
            <article>Some visible content here</article>
        </body>
        </html>
        '''
        
        is_accessible, word_count = bypass.is_content_accessible(html, ContentPlatform.MEDIUM)
        
        # Should extract content from JSON-LD articleBody
        self.assertTrue(is_accessible, f"Expected accessible but got word_count={word_count}")
        self.assertGreater(word_count, 150)  # Should find JSON-LD content
    
    async def test_bypass_module_exports(self):
        """Test that all bypass components are properly exported."""
        from src.bypass import (
            ContentPlatformBypass,
            ContentPlatform,
            PlatformBypassResult,
            bypass_content_platform,
            AntiBotBypass,
            PaywallBypass,
            StealthBrowser,
            ProxyManager,
        )
        
        self.assertIsNotNone(ContentPlatformBypass)
        self.assertIsNotNone(ContentPlatform)
        self.assertIsNotNone(PlatformBypassResult)
        self.assertIsNotNone(bypass_content_platform)
        self.assertIsNotNone(AntiBotBypass)
        self.assertIsNotNone(PaywallBypass)


class TestBypassMetrics(unittest.TestCase):
    """Test metrics tracking for bypass operations."""
    
    def test_platform_bypass_result_has_metadata(self):
        """Test that PlatformBypassResult includes useful metadata."""
        from src.bypass import PlatformBypassResult, ContentPlatform
        
        result = PlatformBypassResult(
            success=True,
            content="Test content",
            platform=ContentPlatform.MEDIUM,
            method_used="playwright",
            content_length=1000,
            metadata={"word_count": 200, "bypass_time_ms": 5000}
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.platform, ContentPlatform.MEDIUM)
        self.assertEqual(result.content_length, 1000)
        self.assertEqual(result.metadata["word_count"], 200)


if __name__ == "__main__":
    unittest.main()
