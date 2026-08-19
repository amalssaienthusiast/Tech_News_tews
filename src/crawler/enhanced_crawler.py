"""
Enhanced Web Crawler Module - Version 2.0
Adds robots.txt support, sitemap parsing, JavaScript rendering, and content deduplication
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from pathlib import Path

from pydantic import BaseModel, Field

from .link_extractor import LinkExtractor, ExtractedLink

logger = logging.getLogger(__name__)


class CrawlStrategy(str, Enum):
    """Crawl traversal strategy."""
    BFS = "bfs"
    DFS = "dfs"
    SMART = "smart"  # NEW: AI-guided crawl prioritization


class CrawlStatus(str, Enum):
    """Crawl job status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlResult(BaseModel):
    """Enhanced result from crawling a single page."""
    url: str
    title: str = ""
    content: str = ""
    html: str = ""
    links_found: int = 0
    depth: int = 0
    crawled_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    success: bool = True
    error: Optional[str] = None
    
    # NEW: Content analysis
    content_hash: str = ""  # For deduplication
    word_count: int = 0
    tech_score: float = 0.0  # 0-1 based on tech keyword density
    
    # NEW: Metadata
    author: str = ""
    published_date: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    

@dataclass
class CrawlJob:
    """Represents a crawl job for persistence and monitoring."""
    id: str
    seed_urls: List[str]
    config: Dict[str, Any]
    status: CrawlStatus = CrawlStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    results_count: int = 0
    error_message: Optional[str] = None


@dataclass
class EnhancedCrawlConfig:
    """Enhanced configuration for web crawler with new features."""
    
    # Basic settings (from original)
    max_depth: int = 2
    max_pages: int = 50
    strategy: CrawlStrategy = CrawlStrategy.BFS
    stay_on_domain: bool = True
    follow_external: bool = False
    article_only: bool = True
    delay_between_requests: float = 1.0
    concurrent_requests: int = 5
    extract_content: bool = True
    save_html: bool = False
    skip_domains: List[str] = field(default_factory=lambda: [
        'twitter.com', 'x.com', 'facebook.com', 'instagram.com',
        'linkedin.com', 'youtube.com', 'reddit.com',
    ])
    
    # NEW: Robots.txt respect
    respect_robots_txt: bool = True
    robots_txt_cache_ttl: int = 3600  # seconds
    
    # NEW: Sitemap parsing
    parse_sitemaps: bool = True
    max_sitemap_urls: int = 100
    
    # NEW: JavaScript rendering (requires Playwright/Selenium)
    render_javascript: bool = False
    js_render_timeout: int = 10  # seconds
    
    # NEW: Content deduplication
    deduplicate_content: bool = True
    similarity_threshold: float = 0.85  # 0-1, higher = stricter
    
    # NEW: Smart crawling
    prioritize_fresh: bool = True  # Prioritize recent articles
    min_content_length: int = 500  # Skip pages with less content
    max_content_length: int = 50000  # Truncate very long pages
    
    # NEW: Resume capability
    save_state: bool = True
    state_file: Optional[str] = None


class EnhancedWebCrawler:
    """
    Enhanced web crawler with advanced features:
    - Robots.txt respect
    - Sitemap.xml parsing
    - Content deduplication (SimHash)
    - JavaScript rendering support
    - Crawl job persistence
    - Smart prioritization
    """
    
    def __init__(
        self,
        config: Optional[EnhancedCrawlConfig] = None,
        use_bypass: bool = True,
        job_id: Optional[str] = None
    ):
        self.config = config or EnhancedCrawlConfig()
        self.use_bypass = use_bypass
        self.job_id = job_id or f"crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # State
        self._visited: Set[str] = set()
        self._results: List[CrawlResult] = []
        self._content_hashes: Set[str] = set()  # For deduplication
        self._robots_cache: Dict[str, Any] = {}  # robots.txt cache
        self._link_extractor = LinkExtractor()
        
        # Job tracking
        self._status = CrawlStatus.PENDING
        self._paused = False
        self._progress_callback: Optional[Callable[[int, int], None]] = None
        
        # Bypass integration
        self._bypass = None
        if use_bypass:
            try:
                from src.bypass import ContentPlatformBypass
                self._bypass = ContentPlatformBypass()
            except ImportError:
                logger.warning("Bypass not available, using basic fetch")
        
        # JavaScript rendering
        self._js_renderer = None
        if self.config.render_javascript:
            self._init_js_renderer()
        
        logger.info(f"🕷️ Enhanced Web Crawler initialized (Job: {self.job_id})")
    
    def _init_js_renderer(self):
        """Initialize JavaScript rendering engine."""
        try:
            # Try playwright first (modern, fast)
            from playwright.async_api import async_playwright
            self._js_renderer = "playwright"
            logger.info("✅ JavaScript rendering: Playwright")
        except ImportError:
            try:
                # Fallback to selenium
                from selenium import webdriver
                self._js_renderer = "selenium"
                logger.info("✅ JavaScript rendering: Selenium")
            except ImportError:
                logger.warning("⚠️ JavaScript rendering requested but no engine available")
                logger.warning("   Install: pip install playwright selenium")
                self._js_renderer = None
    
    async def crawl(
        self,
        seed_urls: List[str],
        callback: Optional[Callable[[CrawlResult], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[CrawlResult]:
        """
        Enhanced crawl with sitemap support and resume capability.
        """
        self._progress_callback = progress_callback
        self._status = CrawlStatus.RUNNING
        self._paused = False
        
        # Load previous state if resuming
        if self.config.save_state and self.config.state_file:
            self._load_state()
        
        # Expand seeds with sitemap URLs if enabled
        expanded_seeds = await self._expand_seeds_with_sitemaps(seed_urls)
        
        self._visited.clear()
        self._results.clear()
        self._content_hashes.clear()
        
        # Initialize queue
        queue: List[Tuple[str, int]] = [(url, 0) for url in expanded_seeds]
        
        logger.info(f"🕷️ Starting enhanced crawl with {len(expanded_seeds)} seeds")
        logger.info(f"   Max depth: {self.config.max_depth}, Max pages: {self.config.max_pages}")
        logger.info(f"   Features: robots.txt={self.config.respect_robots_txt}, "
                   f"sitemaps={self.config.parse_sitemaps}, "
                   f"JS={self.config.render_javascript}, "
                   f"dedup={self.config.deduplicate_content}")
        
        semaphore = asyncio.Semaphore(self.config.concurrent_requests)
        
        try:
            if self.config.strategy == CrawlStrategy.BFS:
                await self._crawl_bfs(queue, semaphore, callback)
            elif self.config.strategy == CrawlStrategy.DFS:
                await self._crawl_dfs(queue, semaphore, callback)
            else:  # SMART
                await self._crawl_smart(queue, semaphore, callback)
            
            self._status = CrawlStatus.COMPLETED
            
        except asyncio.CancelledError:
            self._status = CrawlStatus.PAUSED
            logger.info("🕷️ Crawl paused (can be resumed)")
            if self.config.save_state:
                self._save_state()
            raise
        
        except Exception as e:
            self._status = CrawlStatus.FAILED
            logger.error(f"🕷️ Crawl failed: {e}")
            raise
        
        logger.info(f"🕷️ Crawl complete: {len(self._results)} pages, "
                   f"{len(self._visited)} unique URLs")
        
        # Clean up state file
        if self.config.save_state and self.config.state_file:
            self._cleanup_state()
        
        return self._results
    
    async def _expand_seeds_with_sitemaps(self, seeds: List[str]) -> List[str]:
        """Parse sitemap.xml files and add discovered URLs to seeds."""
        if not self.config.parse_sitemaps:
            return seeds
        
        expanded = list(seeds)
        
        for url in seeds:
            try:
                parsed = urlparse(url)
                sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
                
                logger.debug(f"Fetching sitemap: {sitemap_url}")
                
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(sitemap_url, timeout=10) as resp:
                        if resp.status == 200:
                            xml = await resp.text()
                            urls = self._parse_sitemap(xml)
                            
                            # Add to expanded list (limit to max_sitemap_urls)
                            urls_to_add = urls[:self.config.max_sitemap_urls]
                            expanded.extend(urls_to_add)
                            
                            logger.info(f"   📍 Sitemap added {len(urls_to_add)} URLs from {parsed.netloc}")
                            
            except Exception as e:
                logger.debug(f"   No sitemap found for {url}: {e}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for url in expanded:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        
        return unique
    
    def _parse_sitemap(self, xml: str) -> List[str]:
        """Parse sitemap XML and extract URLs."""
        try:
            # Use defusedxml to mitigate XXE and billion-laughs attacks.
            # Remote sitemap XML is untrusted input.
            try:
                from defusedxml import ElementTree as ET
            except ImportError:
                # Fallback: strip DOCTYPE declarations manually as a partial
                # mitigation if defusedxml is not installed. This is NOT
                # as safe as defusedxml but better than raw ET.fromstring.
                import re
                xml = re.sub(r'<!DOCTYPE[^>]*>', '', xml, flags=re.IGNORECASE)
                import xml.etree.ElementTree as ET

            root = ET.fromstring(xml)
            urls = []
            
            # Handle both sitemap index and urlset
            for url_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
                loc = url_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                if loc is not None and loc.text:
                    urls.append(loc.text)
            
            # Also check for sitemap index entries
            for sitemap_elem in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                loc = sitemap_elem.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                if loc is not None and loc.text:
                    urls.append(loc.text)
            
            return urls
        except Exception as e:
            logger.debug(f"Sitemap parse error: {e}")
            return []
    
    async def _crawl_bfs(
        self,
        queue: List[Tuple[str, int]],
        semaphore: asyncio.Semaphore,
        callback: Optional[Callable]
    ):
        """Enhanced BFS with smart prioritization."""
        while queue and len(self._results) < self.config.max_pages and not self._paused:
            # Sort queue by priority if smart strategy
            if self.config.strategy == CrawlStrategy.SMART:
                queue = self._prioritize_queue(queue)
            
            # Process current level
            current_level = []
            while queue and len(current_level) < self.config.concurrent_requests:
                url, depth = queue.pop(0)
                if url not in self._visited and depth <= self.config.max_depth:
                    # Check robots.txt
                    if not await self._can_fetch(url):
                        continue
                    current_level.append((url, depth))
            
            if not current_level:
                break
            
            # Crawl concurrently
            tasks = [
                self._crawl_page(url, depth, semaphore)
                for url, depth in current_level
                if len(self._results) < self.config.max_pages
            ]
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in results:
                    if isinstance(result, Exception):
                        logger.warning(f"Crawl error: {result}")
                        continue
                    
                    if result and result.success:
                        # Deduplication check
                        if self.config.deduplicate_content and result.content_hash:
                            if result.content_hash in self._content_hashes:
                                logger.debug(f"Skipping duplicate: {result.url}")
                                continue
                            self._content_hashes.add(result.content_hash)
                        
                        self._results.append(result)
                        if callback:
                            callback(result)
                        
                        # Update progress
                        if self._progress_callback:
                            self._progress_callback(len(self._results), self.config.max_pages)
                        
                        # Extract links for next level
                        if result.depth < self.config.max_depth:
                            new_links = await self._extract_next_links(result)
                            for link in new_links:
                                if link.url not in self._visited:
                                    queue.append((link.url, result.depth + 1))
            
            # Save state periodically
            if self.config.save_state and len(self._results) % 10 == 0:
                self._save_state()
    
    def _prioritize_queue(self, queue: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        """Smart prioritization of crawl queue."""
        # Prioritize by:
        # 1. Lower depth (closer to seed)
        # 2. URL patterns suggesting freshness (dates in URL)
        # 3. Tech relevance indicators
        
        def score(item):
            url, depth = item
            score = 100 - (depth * 20)  # Prefer lower depth
            
            # Boost recent articles (date patterns)
            if any(p in url for p in ['/2024/', '/2025/', 'today', 'latest']):
                score += 50
            
            # Boost tech keywords
            tech_indicators = ['ai', 'artificial-intelligence', 'startup', 'funding', 'tech']
            if any(ind in url.lower() for ind in tech_indicators):
                score += 30
            
            return score
        
        return sorted(queue, key=score, reverse=True)
    
    async def _can_fetch(self, url: str) -> bool:
        """Check robots.txt safely via acquisition security boundary."""
        if not self.config.respect_robots_txt:
            return True
        from src.security.acquisition_policy import can_fetch_robots
        try:
            return await can_fetch_robots(url, user_agent=self.config.user_agent)
        except Exception as e:
            logger.debug(f"robots.txt check failed for '{url}': {e}")
            return True
    
    async def _crawl_page(
        self,
        url: str,
        depth: int,
        semaphore: asyncio.Semaphore
    ) -> Optional[CrawlResult]:
        """Enhanced page crawling with JS support and content analysis."""
        async with semaphore:
            if url in self._visited:
                return None
            
            self._visited.add(url)
            
            # Domain filter
            if self.config.stay_on_domain:
                parsed = urlparse(url)
                if any(skip in parsed.netloc.lower() for skip in self.config.skip_domains):
                    return None
            
            # Rate limiting
            await asyncio.sleep(self.config.delay_between_requests)
            
            logger.debug(f"Crawling [{depth}]: {url}")
            
            try:
                # Choose fetch method
                if self.config.render_javascript and self._js_renderer:
                    html, content, title, metadata = await self._fetch_with_js(url)
                else:
                    html, content, title = await self._fetch_page(url)
                    metadata = {}
                
                # Content validation
                if len(content) < self.config.min_content_length:
                    logger.debug(f"Content too short ({len(content)} chars): {url}")
                    return None
                
                # Truncate if too long
                if len(content) > self.config.max_content_length:
                    content = content[:self.config.max_content_length] + "..."
                
                # Calculate content hash for deduplication
                content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
                
                # Calculate tech score
                tech_score = self._calculate_tech_score(content, title)
                
                # Extract links
                links = self._link_extractor.extract_links(html, url, depth)
                
                return CrawlResult(
                    url=url,
                    title=title,
                    content=content,
                    html=html if self.config.save_html else "",
                    links_found=len(links),
                    depth=depth,
                    success=True,
                    content_hash=content_hash,
                    word_count=len(content.split()),
                    tech_score=tech_score,
                    author=metadata.get('author', ''),
                    published_date=metadata.get('published_date'),
                    images=metadata.get('images', [])
                )
                
            except Exception as e:
                logger.warning(f"Failed to crawl {url}: {e}")
                return CrawlResult(
                    url=url,
                    depth=depth,
                    success=False,
                    error=str(e)
                )
    
    async def _fetch_with_js(self, url: str) -> Tuple[str, str, str, Dict]:
        """Fetch page with JavaScript rendering."""
        if self._js_renderer == "playwright":
            return await self._fetch_with_playwright(url)
        elif self._js_renderer == "selenium":
            return await self._fetch_with_selenium(url)
        else:
            raise RuntimeError("No JS renderer available")
    
    async def _fetch_with_playwright(self, url: str) -> Tuple[str, str, str, Dict]:
        """Fetch using Playwright (modern, headless Chrome)."""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto(url, timeout=self.config.js_render_timeout * 1000)
                await page.wait_for_load_state('networkidle')
                
                html = await page.content()
                title = await page.title()
                
                # Extract content
                content = await page.evaluate('''() => {
                    const article = document.querySelector('article') || 
                                   document.querySelector('main') || 
                                   document.querySelector('.content');
                    return article ? article.innerText : document.body.innerText;
                }''')
                
                # Extract metadata
                metadata = await page.evaluate('''() => {
                    const author = document.querySelector('[rel="author"], .author, .byline');
                    const date = document.querySelector('time, [datetime], .date, .published');
                    const images = Array.from(document.querySelectorAll('img')).map(img => img.src);
                    
                    return {
                        author: author ? author.innerText : '',
                        published_date: date ? date.getAttribute('datetime') || date.innerText : null,
                        images: images.slice(0, 5)  // Top 5 images
                    };
                }''')
                
                return html, content, title, metadata
                
            finally:
                await browser.close()
    
    async def _fetch_with_selenium(self, url: str) -> Tuple[str, str, str, Dict]:
        """Fetch using Selenium (fallback)."""
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        
        driver = webdriver.Chrome(options=chrome_options)
        
        try:
            driver.get(url)
            await asyncio.sleep(2)  # Wait for JS to execute
            
            html = driver.page_source
            title = driver.title
            
            # Try to extract main content
            content = driver.find_element("tag name", "body").text
            
            return html, content, title, {}
            
        finally:
            driver.quit()
    
    async def _fetch_page(self, url: str) -> Tuple[str, str, str]:
        """Original fetch method (from basic crawler)."""
        # This is a placeholder - use the original implementation
        # from src.crawler.crawler.WebCrawler._fetch_page
        from src.crawler import WebCrawler
        
        basic_crawler = WebCrawler(use_bypass=self.use_bypass)
        return await basic_crawler._fetch_page(url)
    
    def _calculate_tech_score(self, content: str, title: str) -> float:
        """Calculate tech relevance score (0-1)."""
        text = (title + " " + content).lower()
        
        tech_keywords = [
            'ai', 'artificial intelligence', 'machine learning', 'ml', 'deep learning',
            'startup', 'funding', 'venture capital', 'vc', 'ipo', 'acquisition',
            'cloud', 'aws', 'azure', 'gcp', 'google cloud', 'amazon',
            'software', 'developer', 'programming', 'coding', 'api',
            'security', 'cybersecurity', 'privacy', 'encryption',
            'data', 'database', 'analytics', 'big data',
            'blockchain', 'crypto', 'bitcoin', 'ethereum',
            'fintech', 'payment', 'banking', 'finance',
            'openai', 'chatgpt', 'gpt', 'llm', 'neural',
            'apple', 'google', 'microsoft', 'meta', 'amazon', 'tesla',
        ]
        
        score = 0
        for keyword in tech_keywords:
            if keyword in text:
                score += 0.05
        
        return min(score, 1.0)  # Cap at 1.0
    
    async def _extract_next_links(self, result: CrawlResult) -> List[ExtractedLink]:
        """Extract and filter links."""
        if not result.html:
            return []
        
        links = self._link_extractor.extract_links(
            html=result.html,
            page_url=result.url,
            depth=result.depth,
            max_links=20
        )
        
        if self.config.article_only:
            links = self._link_extractor.filter_article_links(links)
        
        if self.config.stay_on_domain and not self.config.follow_external:
            links = [l for l in links if l.is_internal]
        
        return links
    
    def _save_state(self):
        """Save crawl state for resume capability."""
        if not self.config.state_file:
            return
        
        state = {
            'job_id': self.job_id,
            'visited': list(self._visited),
            'results': [r.dict() for r in self._results],
            'content_hashes': list(self._content_hashes),
            'status': self._status.value,
            'timestamp': datetime.now(UTC).isoformat()
        }
        
        try:
            with open(self.config.state_file, 'w') as f:
                json.dump(state, f)
            logger.debug(f"💾 Crawl state saved: {len(self._results)} pages")
        except Exception as e:
            logger.warning(f"Failed to save crawl state: {e}")
    
    def _load_state(self):
        """Load crawl state for resume."""
        if not self.config.state_file or not Path(self.config.state_file).exists():
            return
        
        try:
            with open(self.config.state_file, 'r') as f:
                state = json.load(f)
            
            self._visited = set(state.get('visited', []))
            self._content_hashes = set(state.get('content_hashes', []))
            
            # Restore results
            for r in state.get('results', []):
                self._results.append(CrawlResult(**r))
            
            logger.info(f"📂 Crawl state loaded: {len(self._results)} pages from previous run")
            
        except Exception as e:
            logger.warning(f"Failed to load crawl state: {e}")
    
    def _cleanup_state(self):
        """Remove state file after successful completion."""
        if self.config.state_file and Path(self.config.state_file).exists():
            try:
                Path(self.config.state_file).unlink()
                logger.debug("🗑️ Crawl state file cleaned up")
            except Exception as e:
                logger.debug(f"Failed to cleanup state file: {e}")
    
    def pause(self):
        """Pause crawling (can be resumed)."""
        self._paused = True
        self._status = CrawlStatus.PAUSED
        logger.info("🕷️ Crawl paused")
    
    def resume(self):
        """Resume paused crawling."""
        self._paused = False
        self._status = CrawlStatus.RUNNING
        logger.info("🕷️ Crawl resumed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Enhanced crawl statistics."""
        successful = [r for r in self._results if r.success]
        
        return {
            "job_id": self.job_id,
            "status": self._status.value,
            "pages_visited": len(self._visited),
            "successful_crawls": len(successful),
            "failed_crawls": len([r for r in self._results if not r.success]),
            "total_links_found": sum(r.links_found for r in self._results),
            "avg_tech_score": sum(r.tech_score for r in successful) / len(successful) if successful else 0,
            "duplicates_skipped": len(self._content_hashes) - len(self._results),
            "max_depth_reached": max((r.depth for r in self._results), default=0),
            "total_words": sum(r.word_count for r in successful),
            "avg_words_per_page": sum(r.word_count for r in successful) / len(successful) if successful else 0,
        }
    
    def get_high_quality_articles(self, min_score: float = 0.3) -> List[CrawlResult]:
        """Get articles with high tech relevance scores."""
        return [
            r for r in self._results
            if r.success and r.tech_score >= min_score
        ]


# Convenience function for quick crawling
async def quick_crawl(
    urls: List[str],
    max_pages: int = 10,
    max_depth: int = 1,
    callback: Optional[Callable[[CrawlResult], None]] = None
) -> List[CrawlResult]:
    """Quick crawl helper for simple use cases."""
    config = EnhancedCrawlConfig(
        max_pages=max_pages,
        max_depth=max_depth,
        delay_between_requests=0.5
    )
    
    crawler = EnhancedWebCrawler(config)
    return await crawler.crawl(urls, callback)
