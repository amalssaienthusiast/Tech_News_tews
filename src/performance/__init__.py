"""
High-Performance Modules for Tech News Scraper

Provides optimized caching and parallel scraping capabilities.
"""

from .cache import FastDeduplicator, TitleDeduplicator
from .parallel_scraper import (
    ParallelScraper,
    ParallelHTTPClient,
    ScraperConfig,
    fetch_urls_parallel,
)

__all__ = [
    "FastDeduplicator",
    "TitleDeduplicator",
    "ParallelScraper",
    "ParallelHTTPClient",
    "ScraperConfig",
    "fetch_urls_parallel",
]
