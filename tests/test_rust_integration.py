"""
Python-Rust Integration Tests

Tests the Rust extension modules and verifies they work correctly with Python.
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_rust_import():
    """Test that Rust extension can be imported."""
    print("Testing Rust import...")
    try:
        import technews
        print(f"✓ Import successful! Version: {technews.version()}")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        print("  Run 'python build_rust.py' to build the extension")
        return False

def test_scraper_basic():
    """Test basic scraper functionality."""
    print("\nTesting RustScraper...")
    try:
        from technews import RustScraper, ScraperConfig
        
        # Test default config
        scraper = RustScraper()
        print("  ✓ Scraper created with defaults")
        
        # Test custom config
        config = ScraperConfig(
            max_connections=10,
            timeout_secs=5,
            enable_pooling=True
        )
        scraper = RustScraper(config)
        print("  ✓ Scraper created with custom config")
        
        # Test fetch (with a fast URL)
        print("  Testing fetch...")
        result = scraper.fetch_url("https://httpbin.org/get")
        
        if result.success:
            print(f"  ✓ Fetch successful! Status: {result.status_code}")
            print(f"  ✓ Response time: {result.response_time_ms:.2f}ms")
            print(f"  ✓ Content length: {len(result.content)} chars")
            return True
        else:
            print(f"  ✗ Fetch failed: {result.error}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_parser():
    """Test HTML parser."""
    print("\nTesting HtmlParser...")
    try:
        from technews import HtmlParser
        
        parser = HtmlParser()
        print("  ✓ Parser created")
        
        html = """
        <html>
            <head>
                <title>Test Article</title>
                <meta name="description" content="Test Description">
            </head>
            <body>
                <h1>Main Heading</h1>
                <p>Paragraph text</p>
                <a href="https://example.com">Link</a>
                <img src="https://example.com/image.jpg">
            </body>
        </html>
        """
        
        result = parser.parse(html, extract_body=True)
        
        print(f"  ✓ Title: {result.title}")
        print(f"  ✓ Description: {result.description}")
        print(f"  ✓ Links found: {len(result.links)}")
        print(f"  ✓ Images found: {len(result.images)}")
        
        if result.title == "Test Article":
            print("  ✓ Parsing correct!")
            return True
        else:
            print(f"  ✗ Incorrect title: {result.title}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_deduplicator():
    """Test URL deduplicator."""
    print("\nTesting Deduplicator...")
    try:
        from technews import Deduplicator
        
        dedup = Deduplicator()
        print("  ✓ Deduplicator created")
        
        urls = [
            "https://example.com/article1",
            "https://example.com/article2",
            "https://example.com/article1",  # Duplicate
            "https://example.com/article3",
            "https://example.com/article2",  # Duplicate
        ]
        
        unique_count = 0
        duplicate_count = 0
        
        for url in urls:
            if dedup.is_duplicate(url):
                duplicate_count += 1
            else:
                unique_count += 1
        
        print(f"  ✓ Processed {len(urls)} URLs")
        print(f"  ✓ Unique: {unique_count}, Duplicates: {duplicate_count}")
        
        if unique_count == 3 and duplicate_count == 2:
            print("  ✓ Deduplication correct!")
            return True
        else:
            print(f"  ✗ Incorrect counts: {unique_count} unique, {duplicate_count} duplicates")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_fingerprint_generator():
    """Test browser fingerprint generator."""
    print("\nTesting FingerprintGenerator...")
    try:
        from technews import FingerprintGenerator
        
        gen = FingerprintGenerator()
        print("  ✓ Generator created")
        
        # Test random profile
        profile = gen.get_random_profile()
        print(f"  ✓ Random profile: {profile.name}")
        print(f"  ✓ User Agent: {profile.user_agent[:50]}...")
        
        # Test get profile
        chrome_profile = gen.get_profile("chrome_windows")
        if chrome_profile:
            print(f"  ✓ Got profile: {chrome_profile.name}")
        
        # Test all profile names
        names = gen.get_profile_names()
        print(f"  ✓ Available profiles: {len(names)}")
        
        return True
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_text_processor():
    """Test text processor."""
    print("\nTesting TextProcessor...")
    try:
        from technews import TextProcessor
        
        processor = TextProcessor()
        print("  ✓ Processor created")
        
        # Test whitespace cleaning
        text = "  hello   world  "
        cleaned = processor.clean_whitespace(text)
        print(f"  ✓ Cleaned: '{cleaned}'")
        
        # Test normalization
        normalized = processor.normalize("  HELLO   WORLD  ")
        print(f"  ✓ Normalized: '{normalized}'")
        
        if normalized == "hello world":
            print("  ✓ Normalization correct!")
            return True
        else:
            print(f"  ✗ Expected 'hello world', got '{normalized}'")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_lru_cache():
    """Test LRU cache."""
    print("\nTesting LRUCache...")
    try:
        from technews import LRUCache
        
        cache = LRUCache(capacity=3)
        print("  ✓ Cache created (capacity=3)")
        
        # Add items
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        print(f"  ✓ Added 3 items, size: {cache.size()}")
        
        # Add fourth item (should evict first)
        cache.set("key4", "value4")
        print(f"  ✓ Added 4th item, size: {cache.size()}")
        
        # Check eviction
        val1 = cache.get("key1")
        val4 = cache.get("key4")
        
        if val1 is None and val4 == "value4":
            print("  ✓ LRU eviction correct!")
            return True
        else:
            print(f"  ✗ Expected key1=None, key4=value4")
            print(f"  ✗ Got key1={val1}, key4={val4}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def benchmark_http():
    """Benchmark HTTP performance."""
    print("\n" + "="*60)
    print("HTTP Performance Benchmark")
    print("="*60)
    
    try:
        from technews import RustScraper
        import requests
        
        scraper = RustScraper()
        urls = ["https://httpbin.org/delay/1"] * 10
        
        # Benchmark Rust
        print("\nBenchmarking Rust (reqwest)...")
        start = time.time()
        for url in urls:
            scraper.fetch_url(url)
        rust_time = time.time() - start
        print(f"  Rust: {rust_time:.2f}s for {len(urls)} requests")
        
        # Benchmark Python
        print("\nBenchmarking Python (requests)...")
        start = time.time()
        for url in urls:
            requests.get(url, timeout=5)
        python_time = time.time() - start
        print(f"  Python: {python_time:.2f}s for {len(urls)} requests")
        
        # Calculate speedup
        speedup = python_time / rust_time
        print(f"\n🚀 Speedup: {speedup:.2f}x")
        
        if speedup > 1.5:
            print("✓ Rust is significantly faster!")
        else:
            print("⚠ Speedup below target (1.5x)")
        
        return True
        
    except Exception as e:
        print(f"✗ Benchmark error: {e}")
        return False

def main():
    """Run all integration tests."""
    print("=" * 60)
    print("  Rust-Python Integration Tests")
    print("=" * 60)
    
    # Run tests
    results = []
    results.append(("Import", test_rust_import()))
    results.append(("Scraper", test_scraper_basic()))
    results.append(("Parser", test_parser()))
    results.append(("Deduplicator", test_deduplicator()))
    results.append(("Fingerprint", test_fingerprint_generator()))
    results.append(("Text Processor", test_text_processor()))
    results.append(("LRU Cache", test_lru_cache()))
    
    # Benchmark
    results.append(("Benchmark", benchmark_http()))
    
    # Summary
    print("\n" + "=" * 60)
    print("  Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status} - {name}")
    
    print(f"\n  {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
