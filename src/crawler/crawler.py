"""
Web Crawler for Tech News Scraper v4.0

Intelligent web crawler with configurable traversal strategies,
depth control, and integration with existing bypass mechanisms.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .link_extractor import LinkExtractor, ExtractedLink

logger = logging.getLogger(__name__)


class CrawlStrategy(str, Enum):
    """Crawl traversal strategy."""
    BFS = "bfs"  # Breadth-first: explore all links at current depth first
    DFS = "dfs"  # Depth-first: follow links deeply before backtracking


class CrawlResult(BaseModel):
    """Result from crawling a single page."""
    url: str
    title: str = ""
    content: str = ""
    html: str = ""
    links_found: int = 0
    depth: int = 0
    crawled_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    success: bool = True
    error: Optional[str] = None


@dataclass
class CrawlConfig:
    """Configuration for web crawler."""
    
    # Traversal settings
    max_depth: int = 2                 # Maximum crawl depth (0 = seed only)
    max_pages: int = 50                # Maximum pages to crawl
    strategy: CrawlStrategy = CrawlStrategy.BFS
    
    # Filtering
    stay_on_domain: bool = True        # Only crawl within initial domain
    follow_external: bool = False       # Follow external links
    article_only: bool = True          # Only crawl pages that look like articles
    
    # Rate limiting
    delay_between_requests: float = 1.0  # Seconds between requests
    concurrent_requests: int = 5         # Max concurrent requests
    
    # Content
    extract_content: bool = True       # Extract article content
    save_html: bool = False            # Save raw HTML
    
    # Domains to always skip
    skip_domains: List[str] = field(default_factory=lambda: [
        'twitter.com', 'x.com', 'facebook.com', 'instagram.com',
        'linkedin.com', 'youtube.com', 'reddit.com',
    ])


class WebCrawler:
    """
    Asynchronous web crawler with intelligent link following.
    
    Features:
    - BFS/DFS traversal strategies
    - Configurable depth and page limits
    - Integration with bypass mechanisms
    - Article detection and filtering
    - Rate limiting and polite crawling
    """
    
    def __init__(
        self,
        config: Optional[CrawlConfig] = None,
        use_bypass: bool = True
    ):
        """
        Initialize web crawler.
        
        Args:
            config: Crawl configuration
            use_bypass: Use bypass mechanisms for protected sites
        """
        self.config = config or CrawlConfig()
        self.use_bypass = use_bypass
        
        # State
        self._visited: Set[str] = set()
        self._results: List[CrawlResult] = []
        self._link_extractor = LinkExtractor()
        
        # Bypass integration
        self._bypass = None
        if use_bypass:
            try:
                from src.bypass import ContentPlatformBypass
                self._bypass = ContentPlatformBypass()
            except ImportError:
                logger.warning("Bypass not available, using basic fetch")
    
    async def crawl(
        self,
        seed_urls: List[str],
        callback: Optional[Callable[[CrawlResult], None]] = None
    ) -> List[CrawlResult]:
        """
        Crawl starting from seed URLs.
        
        Args:
            seed_urls: Starting URLs to crawl
            callback: Optional callback for each crawled page
            
        Returns:
            List of CrawlResult objects
        """
        self._visited.clear()
        self._results.clear()
        self._link_extractor.clear_seen()
        
        # Initialize queue with seeds
        queue: List[tuple[str, int]] = [(url, 0) for url in seed_urls]
        
        logger.info(f"Starting crawl with {len(seed_urls)} seeds, max_depth={self.config.max_depth}")
        
        semaphore = asyncio.Semaphore(self.config.concurrent_requests)
        
        if self.config.strategy == CrawlStrategy.BFS:
            await self._crawl_bfs(queue, semaphore, callback)
        else:
            await self._crawl_dfs(queue, semaphore, callback)
        
        logger.info(f"Crawl complete: {len(self._results)} pages crawled")
        return self._results
    
    async def _crawl_bfs(
        self,
        queue: List[tuple[str, int]],
        semaphore: asyncio.Semaphore,
        callback: Optional[Callable]
    ):
        """Breadth-first crawl implementation."""
        while queue and len(self._results) < self.config.max_pages:
            # Process current level
            current_level = []
            next_level = []
            
            while queue:
                url, depth = queue.pop(0)
                if url not in self._visited and depth <= self.config.max_depth:
                    current_level.append((url, depth))
            
            # Crawl current level concurrently
            tasks = []
            for url, depth in current_level:
                if len(self._results) >= self.config.max_pages:
                    break
                tasks.append(self._crawl_page(url, depth, semaphore))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in results:
                    if isinstance(result, Exception):
                        logger.warning(f"Crawl error: {result}")
                        continue
                    
                    if result and result.success:
                        self._results.append(result)
                        if callback:
                            callback(result)
                        
                        # Extract links for next level
                        if result.depth < self.config.max_depth:
                            new_links = await self._extract_next_links(result)
                            for link in new_links:
                                if link.url not in self._visited:
                                    queue.append((link.url, result.depth + 1))
    
    async def _crawl_dfs(
        self,
        queue: List[tuple[str, int]],
        semaphore: asyncio.Semaphore,
        callback: Optional[Callable]
    ):
        """Depth-first crawl implementation."""
        stack = queue.copy()
        
        while stack and len(self._results) < self.config.max_pages:
            url, depth = stack.pop()
            
            if url in self._visited or depth > self.config.max_depth:
                continue
            
            result = await self._crawl_page(url, depth, semaphore)
            
            if result and result.success:
                self._results.append(result)
                if callback:
                    callback(result)
                
                # Extract and add links to stack (reverse for DFS order)
                if result.depth < self.config.max_depth:
                    new_links = await self._extract_next_links(result)
                    for link in reversed(new_links):
                        if link.url not in self._visited:
                            stack.append((link.url, result.depth + 1))
    
    async def _crawl_page(
        self,
        url: str,
        depth: int,
        semaphore: asyncio.Semaphore
    ) -> Optional[CrawlResult]:
        """Crawl a single page."""
        async with semaphore:
            if url in self._visited:
                return None
            
            self._visited.add(url)
            
            # Check domain filter
            if self.config.stay_on_domain:
                parsed = urlparse(url)
                if any(skip in parsed.netloc.lower() for skip in self.config.skip_domains):
                    return None
            
            # Rate limiting
            await asyncio.sleep(self.config.delay_between_requests)
            
            logger.debug(f"Crawling [{depth}]: {url}")
            
            try:
                html, content, title = await self._fetch_page(url)
                
                return CrawlResult(
                    url=url,
                    title=title,
                    content=content if self.config.extract_content else "",
                    html=html if self.config.save_html else "",
                    links_found=len(self._link_extractor.extract_links(html, url, depth)),
                    depth=depth,
                    success=True
                )
                
            except Exception as e:
                logger.warning(f"Failed to crawl {url}: {e}")
                return CrawlResult(
                    url=url,
                    depth=depth,
                    success=False,
                    error=str(e)
                )
    
    async def _fetch_page(self, url: str) -> tuple[str, str, str]:
        """Fetch page content using bypass or aiohttp."""
        html = ""
        content = ""
        title = ""
        
        if self._bypass:
            try:
                result = await self._bypass.get_article_content(url)
                if result:
                    html = result.get('html', '')
                    content = result.get('content', '')
                    title = result.get('title', '')
                    return html, content, title
            except Exception as e:
                logger.debug(f"Bypass failed, falling back to aiohttp: {e}")
        
        # Fallback to aiohttp
        import aiohttp
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    title_tag = soup.find('title')
                    title = title_tag.get_text(strip=True) if title_tag else ""
                    
                    # Extract main content
                    for selector in ['article', 'main', '.content', '.post-content']:
                        main = soup.select_one(selector)
                        if main:
                            content = main.get_text(separator=' ', strip=True)
                            break
                    
                    if not content:
                        content = soup.get_text(separator=' ', strip=True)[:5000]
        
        return html, content, title
    
    async def _extract_next_links(
        self,
        result: CrawlResult
    ) -> List[ExtractedLink]:
        """Extract links to follow from a crawl result."""
        if not result.html:
            return []
        
        links = self._link_extractor.extract_links(
            html=result.html,
            page_url=result.url,
            depth=result.depth,
            max_links=20
        )
        
        # Filter based on config
        if self.config.article_only:
            links = self._link_extractor.filter_article_links(links)
        
        if self.config.stay_on_domain and not self.config.follow_external:
            links = [l for l in links if l.is_internal]
        
        return links
    
    def get_stats(self) -> Dict[str, Any]:
        """Get crawl statistics."""
        return {
            "pages_visited": len(self._visited),
            "successful_crawls": len([r for r in self._results if r.success]),
            "failed_crawls": len([r for r in self._results if not r.success]),
            "total_links_found": sum(r.links_found for r in self._results),
            "max_depth_reached": max((r.depth for r in self._results), default=0)
        }
    
    def get_article_urls(self) -> List[str]:
        """Get all successfully crawled article URLs."""
        return [r.url for r in self._results if r.success]


# Convenience function
async def crawl_site(
    seed_url: str,
    max_depth: int = 2,
    max_pages: int = 50
) -> List[CrawlResult]:
    """
    Quick crawl of a site.
    
    Args:
        seed_url: Starting URL
        max_depth: Maximum depth
        max_pages: Maximum pages
        
    Returns:
        List of CrawlResult
    """
    config = CrawlConfig(
        max_depth=max_depth,
        max_pages=max_pages,
        strategy=CrawlStrategy.BFS
    )
    crawler = WebCrawler(config)
    return await crawler.crawl([seed_url])
