
import asyncio
import logging
import sys
import os
import pytest

# Add project root to path
sys.path.append(os.getcwd())

from src.engine.url_analyzer import URLAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO)

@pytest.mark.asyncio
async def test_medium_pipeline():
    url = "https://medium.com/write-a-catalyst/as-a-neuroscientist-i-quit-these-5-morning-habits-that-destroy-your-brain-3efe1f410226"
    print(f"Testing Medium Pipeline with URL: {url}")
    
    analyzer = URLAnalyzer()
    
    try:
        result = await analyzer.analyze(url)
        
        if result:
            print("\n✅ Analysis Successful!")
            print(f"Title: {result.article.title}")
            print(f"Source: {result.article.source}")
            print(f"Reading Time: {result.reading_time_min} min")
            print(f"Word Count: {len(result.article.content.split())}")
            print(f"Content Preview: {result.article.content[:500]}...")
            
            # Check for success indicators
            if len(result.article.content) > 1000 and "Sign in" not in result.article.content[:500]:
                 print("✅ Content appears clean and substantial.")
            else:
                 print("⚠️ Content might be incomplete or contain login prompts.")
                 
            # Print formatted report
            print("\n--- Report ---\n")
            print(analyzer.format_analysis_report(result))
            
        else:
            print("\n❌ Analysis Failed: No result returned.")
            
    except Exception as e:
        print(f"\n❌ Exception during analysis: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await analyzer.close()

if __name__ == "__main__":
    asyncio.run(test_medium_pipeline())
