"""
Web Crawler Module for Tech News Scraper v4.0+Enhanced

Provides intelligent web crawling capabilities:
- BFS/DFS crawling with configurable depth
- Intelligent link extraction  
- Domain filtering and rate limiting
- Integration with existing bypass mechanisms

ENHANCED FEATURES (v2.0):
- Robots.txt respect
- Sitemap.xml parsing
- JavaScript rendering support
- Content deduplication
- Smart prioritization
- Resume capability
"""

# Original crawler (v1.0)
from .crawler import WebCrawler, CrawlConfig, CrawlResult, CrawlStrategy
from .link_extractor import LinkExtractor, ExtractedLink

# Enhanced crawler (v2.0) - NEW!
from .enhanced_crawler import (
    EnhancedWebCrawler,
    EnhancedCrawlConfig,
    CrawlJob,
    CrawlStatus,
    CrawlResult as EnhancedCrawlResult,
    quick_crawl,
)

__all__ = [
    # Original (stable)
    "WebCrawler",
    "CrawlConfig",
    "CrawlResult",
    "CrawlStrategy",
    "LinkExtractor",
    "ExtractedLink",
    # Enhanced (NEW)
    "EnhancedWebCrawler",
    "EnhancedCrawlConfig",
    "CrawlJob",
    "CrawlStatus",
    "EnhancedCrawlResult",
    "quick_crawl",
]