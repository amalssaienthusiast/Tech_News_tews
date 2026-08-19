"""
Google Search Engine Diagnostic Tool
Tests Google Custom Search API integration and reports issues.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
import pytest
from config.settings import GOOGLE_API_KEY, GOOGLE_CSE_ID
from src.sources.google_news import GoogleCustomSearchClient
from src.discovery import DiscoveryAgent


def check_configuration():
    """Check if Google API is properly configured."""
    print("\n" + "="*60)
    print("🔍 GOOGLE SEARCH ENGINE DIAGNOSTIC REPORT")
    print("="*60 + "\n")
    
    issues = []
    warnings_list = []
    
    # Check 1: API Key exists
    print("1. Checking API Key Configuration...")
    if not GOOGLE_API_KEY:
        issues.append("❌ GOOGLE_API_KEY is not set")
        print("   ❌ GOOGLE_API_KEY: NOT SET")
    else:
        key_valid = GOOGLE_API_KEY.startswith("AIza") and len(GOOGLE_API_KEY) > 30
        if key_valid:
            print(f"   ✅ GOOGLE_API_KEY: Set ({GOOGLE_API_KEY[:10]}...)")
        else:
            issues.append("⚠️ GOOGLE_API_KEY format appears invalid (should start with 'AIza')")
            print(f"   ⚠️ GOOGLE_API_KEY: Set but format looks invalid ({GOOGLE_API_KEY[:10]}...)")
    
    # Check 2: CSE ID exists
    print("\n2. Checking Custom Search Engine ID...")
    if not GOOGLE_CSE_ID:
        issues.append("❌ GOOGLE_CSE_ID is not set")
        print("   ❌ GOOGLE_CSE_ID: NOT SET")
    else:
        print(f"   ✅ GOOGLE_CSE_ID: Set ({GOOGLE_CSE_ID[:10]}...)")
    
    # Check 3: Client initialization
    print("\n3. Testing Client Initialization...")
    try:
        client = GoogleCustomSearchClient()
        if client.is_enabled:
            print("   ✅ GoogleCustomSearchClient initialized successfully")
            print(f"   📊 Enabled: {client.is_enabled}")
        else:
            issues.append("❌ GoogleCustomSearchClient is disabled (missing API key or CSE ID)")
            print("   ❌ GoogleCustomSearchClient is DISABLED")
    except Exception as e:
        issues.append(f"❌ Client initialization failed: {e}")
        print(f"   ❌ Initialization error: {e}")
    
    # Check 4: Discovery Agent
    print("\n4. Testing Discovery Agent Integration...")
    try:
        agent = DiscoveryAgent()
        google_available = agent.api_available.get("google", False)
        if google_available:
            print("   ✅ Discovery Agent reports Google API as available")
        else:
            warnings_list.append("⚠️ Discovery Agent reports Google API as unavailable")
            print("   ⚠️ Discovery Agent: Google API unavailable")
    except Exception as e:
        warnings_list.append(f"⚠️ Discovery Agent check failed: {e}")
        print(f"   ⚠️ Discovery Agent error: {e}")
    
    return issues, warnings_list


@pytest.mark.asyncio
async def test_api_connection():
    """Test actual API connection with a simple search."""
    print("\n5. Testing Live API Connection...")
    
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("   ⏭️  Skipping (API keys not configured)")
        return None
    
    client = GoogleCustomSearchClient()
    
    if not client.is_enabled:
        print("   ⏭️  Skipping (client disabled)")
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            results = await client.search(
                session=session,
                query="technology news",
                num_results=3,
                date_restrict="d1"
            )
            
            if results:
                print(f"   ✅ API Connection successful!")
                print(f"   📰 Retrieved {len(results)} articles")
                print(f"\n   Sample results:")
                for i, article in enumerate(results[:2], 1):
                    print(f"      {i}. {article.title[:60]}...")
                    print(f"         Source: {article.source}")
                return True
            else:
                print("   ⚠️  API connected but returned no results")
                return False
                
    except aiohttp.ClientError as e:
        print(f"   ❌ Connection error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ API test failed: {e}")
        return False


def check_common_issues():
    """Check for common configuration issues."""
    print("\n6. Checking for Common Issues...")
    
    issues = []
    
    # Check if using free tier limits
    print("   ℹ️  Free tier: 100 queries/day")
    
    # Check if CSE is configured for news
    print("   ℹ️  Ensure your CSE is configured to search news sites")
    
    # Check for common errors
    if GOOGLE_API_KEY and len(GOOGLE_API_KEY) < 20:
        issues.append("API key appears too short (should be ~39 characters)")
    
    # Check .env file exists
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        issues.append(".env file not found (create one from .env.example)")
    
    if issues:
        for issue in issues:
            print(f"   ⚠️  {issue}")
    else:
        print("   ✅ No obvious configuration issues detected")
    
    return issues


async def main():
    """Run all diagnostics."""
    config_issues, warnings_list = check_configuration()
    api_status = await test_api_connection()
    common_issues = check_common_issues()
    
    # Summary
    print("\n" + "="*60)
    print("📊 DIAGNOSTIC SUMMARY")
    print("="*60 + "\n")
    
    all_issues = config_issues + common_issues
    
    if not GOOGLE_API_KEY and not GOOGLE_CSE_ID:
        print("🔴 STATUS: NOT CONFIGURED")
        print("\n   Google Search API is not configured.")
        print("   The system will use RSS feeds and web scraping fallback.")
        print("\n   To enable:")
        print("   1. Get API key: https://developers.google.com/custom-search/v1/overview")
        print("   2. Create CSE: https://programmablesearchengine.google.com/")
        print("   3. Add to .env file:")
        print("      GOOGLE_API_KEY=your_key_here")
        print("      GOOGLE_CSE_ID=your_cse_id_here")
        
    elif all_issues:
        print("🟡 STATUS: ISSUES DETECTED")
        print(f"\n   Found {len(all_issues)} issue(s):")
        for issue in all_issues:
            print(f"   {issue}")
            
        if warnings_list:
            print(f"\n   Additional warnings ({len(warnings_list)}):")
            for warning in warnings_list:
                print(f"   {warning}")
                
    elif api_status is True:
        print("🟢 STATUS: FULLY OPERATIONAL")
        print("\n   ✅ Google Search API is working correctly")
        print("   ✅ Configuration is valid")
        print("   ✅ API connection successful")
        
        if warnings_list:
            print(f"\n   Minor warnings ({len(warnings_list)}):")
            for warning in warnings_list:
                print(f"   {warning}")
                
    elif api_status is False:
        print("🟠 STATUS: CONFIGURED BUT NOT RESPONDING")
        print("\n   ⚠️  API keys are set but connection test failed")
        print("   Possible causes:")
        print("   • API quota exceeded (100/day free tier)")
        print("   • Invalid API key or CSE ID")
        print("   • Network connectivity issues")
        print("   • Billing not enabled (if using paid tier)")
        
    else:
        print("⚪ STATUS: UNKNOWN")
        print("\n   Could not determine status (connection test skipped)")
    
    print("\n" + "="*60)
    print("For more details, check:")
    print("  • logs/ directory for error logs")
    print("  • .env file for configuration")
    print("  • https://console.cloud.google.com/apis/credentials")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
