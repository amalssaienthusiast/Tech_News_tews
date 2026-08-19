"""
Performance Benchmarking Script

Compare performance between old and new scraping methods.
"""

import asyncio
import time
import requests
from typing import List, Dict

# Test URLs
TEST_URLS = [
    "https://www.rust-lang.org",
    "https://www.python.org",
    "https://crates.io",
    "https://pypi.org",
] * 10  # Repeat 10 times for meaningful statistics


def benchmark_requests(urls: List[str]) -> Dict[str, float]:
    """
    Benchmark synchronous requests library.
    
    Args:
        urls: List of URLs to fetch
        
    Returns:
        Dictionary with timing stats
    """
    print("Benchmarking requests (sync)...")
    start = time.time()
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; NewsAggregator/1.0)"
    })
    
    success_count = 0
    for url in urls:
        try:
            response = session.get(url, timeout=10)
            if response.status_code == 200:
                success_count += 1
        except Exception as e:
            pass
    
    elapsed = time.time() - start
    
    return {
        "method": "requests (sync)",
        "total_urls": len(urls),
        "success_count": success_count,
        "elapsed": elapsed,
        "per_url": elapsed / len(urls),
    }


async def benchmark_aiohttp(urls: List[str]) -> Dict[str, float]:
    """
    Benchmark asynchronous aiohttp library.
    
    Args:
        urls: List of URLs to fetch
        
    Returns:
        Dictionary with timing stats
    """
    print("Benchmarking aiohttp (async)...")
    start = time.time()
    
    import aiohttp
    
    from src.utils.http import create_connector
    connector = create_connector(limit=50)
    timeout = aiohttp.ClientTimeout(total=10)
    
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NewsAggregator/1.0)"},
    ) as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=False)
        
        success_count = len([r for r in responses if isinstance(r, aiohttp.ClientResponse) and r.status == 200])
    
    elapsed = time.time() - start
    
    return {
        "method": "aiohttp (async)",
        "total_urls": len(urls),
        "success_count": success_count,
        "elapsed": elapsed,
        "per_url": elapsed / len(urls),
    }


def benchmark_parallel(urls: List[str]) -> Dict[str, float]:
    """
    Benchmark new parallel scraper.
    
    Args:
        urls: List of URLs to fetch
        
    Returns:
        Dictionary with timing stats
    """
    print("Benchmarking ParallelScraper (optimized async)...")
    
    async def run():
        from src.performance.parallel_scraper import fetch_urls_parallel
        
        results = await fetch_urls_parallel(
            urls=urls,
            max_concurrent=50,
            timeout=10
        )
        
        success_count = len([r for r in results if r and r.get("success")])
        
        return {
            "method": "ParallelScraper (optimized)",
            "total_urls": len(urls),
            "success_count": success_count,
            "elapsed": time.time() - time.time(),  # Placeholder, will be set
            "per_url": 0,
        }
    
    start = time.time()
    asyncio.run(run())
    elapsed = time.time() - start
    
    return {
        "method": "ParallelScraper (optimized)",
        "total_urls": len(urls),
        "success_count": success_count,
        "elapsed": elapsed,
        "per_url": elapsed / len(urls),
    }


def benchmark_deduplication():
    """
    Benchmark URL deduplication methods.
    """
    print("\n=== Deduplication Benchmark ===\n")
    
    # Generate test URLs
    test_urls = [f"https://example.com/article{i}" for i in range(10000)]
    
    # Benchmark set-based deduplication
    print("Benchmarking set-based deduplication...")
    start = time.time()
    
    seen_set = set()
    for url in test_urls:
        _ = url in seen_set
        seen_set.add(url)
    
    set_time = time.time() - start
    
    # Benchmark LRU cache deduplication
    print("Benchmarking LRU cache deduplication...")
    start = time.time()
    
    from src.performance.cache import FastDeduplicator
    
    dedup = FastDeduplicator(max_size=10000)
    for url in test_urls:
        _ = dedup.is_duplicate(url)
        dedup.add(url)
    
    cache_time = time.time() - start
    
    speedup = set_time / cache_time if cache_time > 0 else 1
    
    print(f"\nDeduplication Results:")
    print(f"  Set-based:     {set_time:.3f}s ({10000/set_time:.0f} ops/sec)")
    print(f"  LRU cache:     {cache_time:.3f}s ({10000/cache_time:.0f} ops/sec)")
    print(f"  Speedup:       {speedup:.2f}x")
    print(f"  Stats:         {dedup.get_stats()}")


def run_all_benchmarks():
    """
    Run all performance benchmarks.
    """
    print("=" * 60)
    print("  Tech News Scraper - Performance Benchmarks")
    print("=" * 60)
    
    # HTTP scraping benchmarks
    print("\n=== HTTP Scraping Benchmarks ===\n")
    
    results = []
    
    # Run requests benchmark
    results.append(benchmark_requests(TEST_URLS))
    
    # Run aiohttp benchmark
    results.append(asyncio.run(benchmark_aiohttp(TEST_URLS)))
    
    # Run parallel scraper benchmark
    try:
        results.append(benchmark_parallel(TEST_URLS))
    except ImportError:
        print("ParallelScraper not available, skipping...")
    
    # Print HTTP benchmark results
    print("\nHTTP Scraping Results:")
    print("-" * 60)
    print(f"{'Method':<30} {'Total':>8} {'Success':>8} {'Time':>8} {'Per URL':>10} {'Speedup':>8}")
    print("-" * 60)
    
    baseline = results[0]['elapsed']
    
    for result in results:
        speedup = baseline / result['elapsed'] if result['elapsed'] > 0 else 0
        print(
            f"{result['method']:<30} "
            f"{result['total_urls']:>8} "
            f"{result['success_count']:>8} "
            f"{result['elapsed']:>8.2f}s "
            f"{result['per_url']:>10.4f}s "
            f"{speedup:>8.2f}x"
        )
    
    print("-" * 60)
    
    # Deduplication benchmarks
    benchmark_deduplication()
    
    print("\n" + "=" * 60)
    print("  Benchmarking Complete!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_benchmarks()
