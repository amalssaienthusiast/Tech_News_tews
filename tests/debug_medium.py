#!/usr/bin/env python3
"""
Debug script to see what content is actually being extracted.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


async def debug_medium():
    """Debug what content is being extracted."""
    
    test_url = "https://medium.com/gitconnected/why-nasa-developers-write-code-completely-differently-and-why-you-should-too-68e07623ffa7"
    
    print("=" * 70)
    print("DEBUG: Checking raw page content")
    print("=" * 70)
    
    try:
        from src.bypass.browser_engine import StealthBrowser
        from bs4 import BeautifulSoup
        
        browser = StealthBrowser(headless=True)
        await browser.initialize()
        
        try:
            page = await browser.new_page()
            
            print(f"\nNavigating to: {test_url}")
            await page.goto(test_url, wait_until="networkidle", timeout=45000)
            
            # Wait for article to load
            print("Waiting for article content...")
            await asyncio.sleep(3)
            
            # Try to wait for article element
            try:
                await page.wait_for_selector('article', timeout=10000)
                print("✓ Found article element")
            except Exception as e:
                print(f"✗ No article element found: {e}")
            
            content = await page.content()
            print(f"\nTotal HTML length: {len(content)} chars")
            
            # Parse and extract
            soup = BeautifulSoup(content, 'html.parser')
            
            # Check what elements exist
            print("\n--- Element Check ---")
            for sel in ['article', '.postArticle-content', 'section[data-field="body"]', '.section-inner', 'main']:
                els = soup.select(sel)
                if els:
                    text = els[0].get_text(strip=True)[:200]
                    print(f"✓ {sel}: found {len(els)} element(s), text preview: {text[:100]}...")
                else:
                    print(f"✗ {sel}: not found")
            
            # Find any element with substantial text
            print("\n--- Looking for readable content ---")
            for tag in soup.find_all(['article', 'section', 'div', 'main']):
                text = tag.get_text(separator=' ', strip=True)
                words = text.split()
                if len(words) > 100:
                    classes = tag.get('class', [])
                    class_str = '.'.join(classes) if classes else '(no class)'
                    print(f"✓ {tag.name}.{class_str}: {len(words)} words")
                    print(f"  Preview: {text[:200]}...")
                    break
            
            await page.close()
            
        finally:
            await browser.close()
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_medium())
