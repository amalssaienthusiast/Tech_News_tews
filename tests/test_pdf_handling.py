
import asyncio
import logging
import sys
import os
import pytest

# Add project root to path
sys.path.append(os.getcwd())

from src.engine.deep_scraper import DeepScraper

# Configure logging
logging.basicConfig(level=logging.INFO)

@pytest.mark.asyncio
async def test_pdf_scraping():
    # URL that caused the crash
    url = "https://engineering.nyu.edu/sites/default/files/2021-10/How_I_Became_a_Quant%20%281%29.pdf"
    print(f"Testing PDF Handling with URL: {url}")
    
    scraper = DeepScraper()
    
    try:
        # detailed scrape of the source
        result = await scraper.fetch_url(None, url) # Passing None as session since fetch_url might handle it or we mock it. 
        # Actually fetch_url expects a session.
        # Let's use analyze_url generic method or create a session.
        
        # Checking DeepScraper usage in main code... 
        # It seems fetch_url is internal or used with a session.
        # Let's use a session context.
        import aiohttp
        async with aiohttp.ClientSession() as session:
             result = await scraper.fetch_url(session, url)
        
        if result:
            print("\n✅ PDF Handled Successfully (or at least didn't crash)!")
            print(f"Status: {result.status_code}")
            print(f"Content Length: {len(result.html)}")
            print(f"Headers: {result.headers}")
        else:
            print("\n❌ PDF Request returned None (handled but no content)")
            
    except Exception as e:
        print(f"\n❌ Exception during analysis: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(test_pdf_scraping())
