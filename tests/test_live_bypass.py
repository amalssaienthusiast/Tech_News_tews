#!/usr/bin/env python3
"""
Live test script for Content Platform Bypass.

Tests the bypass against a real Medium URL.
Can be run standalone or via pytest with pytest-asyncio.
"""

import asyncio
import sys
import unittest
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.bypass.content_platform_bypass import (
    ContentPlatformBypass,
    ContentPlatform,
    bypass_content_platform,
)


class TestLiveBypass(unittest.IsolatedAsyncioTestCase):
    """Live bypass tests using IsolatedAsyncioTestCase for pytest compatibility."""
    
    async def test_medium_url(self):
        """Test bypass against live Medium URL."""
        
        test_url = "https://medium.com/gitconnected/why-nasa-developers-write-code-completely-differently-and-why-you-should-too-68e07623ffa7"
        
        async with ContentPlatformBypass() as bypass:
            # Detect platform
            platform = bypass.detect_platform(test_url)
            self.assertEqual(platform, ContentPlatform.MEDIUM)
            
            # Test with auto strategy
            result = await bypass.bypass(test_url, strategy="auto")
            
            # Verify we got some content (live test may vary)
            self.assertIsNotNone(result)
            self.assertIsNotNone(result.content_length)
            
            # If successful, verify substantial content
            if result.success:
                self.assertGreater(result.content_length, 10000)


async def run_live_test():
    """Standalone test runner with verbose output."""
    
    test_url = "https://medium.com/gitconnected/why-nasa-developers-write-code-completely-differently-and-why-you-should-too-68e07623ffa7"
    
    print("=" * 70)
    print("CONTENT PLATFORM BYPASS - LIVE TEST")
    print("=" * 70)
    print(f"\nTarget URL: {test_url}")
    
    start = time.time()
    
    async with ContentPlatformBypass() as bypass:
        # Detect platform
        platform = bypass.detect_platform(test_url)
        print(f"\nDetected Platform: {platform.value}")
        
        # Test with Playwright first
        print("\n--- Testing Playwright Strategy ---")
        result = await bypass.bypass(test_url, strategy="playwright")
        
        print(f"Success: {result.success}")
        print(f"Method Used: {result.method_used}")
        print(f"Content Length: {result.content_length} chars")
        print(f"Bypass Time: {result.bypass_time_ms:.0f}ms")
        
        if result.error:
            print(f"Error: {result.error}")
        
        if result.success and result.content:
            # Extract a snippet
            content = result.content
            
            # Try to find article text
            article_start = content.find("<article")
            if article_start > 0:
                snippet_start = article_start
                snippet = content[snippet_start:snippet_start + 500]
                print(f"\n--- Content Snippet (first 500 chars of article) ---")
                print(snippet[:500] + "...")
            else:
                print(f"\n--- Content Snippet (raw HTML start) ---")
                print(content[500:1000] + "...")
        
        # If Playwright failed, try HTTP
        if not result.success:
            print("\n--- Falling back to HTTP Strategy ---")
            result = await bypass.bypass(test_url, strategy="http")
            
            print(f"Success: {result.success}")
            print(f"Method Used: {result.method_used}")
            print(f"Content Length: {result.content_length} chars")
            
            if result.error:
                print(f"Error: {result.error}")
    
    print("\n" + "=" * 70)
    print(f"TEST COMPLETE (Total time: {time.time() - start:.1f}s)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_live_test())
