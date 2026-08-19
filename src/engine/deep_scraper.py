"""
Deep Scraper Engine for multi-layer content extraction.

This module provides advanced web scraping capabilities:
- Multi-layer link discovery algorithm
- Content quality scoring
- Source reputation tracking
- Async batch processing with rate limiting
- NO RSS SUPPORT - direct web scraping only
"""

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

# Local imports
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.types import (
    Article,
    ScrapingResult,
    ScrapingStatus,
    Source,
    SourceTier,
    TechScore,
)
from src.core.exceptions import (
    ScrapingError,
    ContentExtractionError,
    RateLimitedError,
    InvalidURLError,
)
from src.utils.http import create_connector
from src.data_structures import (
    BloomFilter,
    URLDeduplicator,
    LRUCache,
    HTTPResponseCache,
    TechKeywordMatcher,
    TechKeywordMatcher,
    SourcePriorityQueue,
)
from src.bypass.anti_bot import AntiBotBypass
from src.bypass.content_platform_bypass import ContentPlatformBypass, ContentPlatform

logger = logging.getLogger(__name__)


@dataclass
class ScrapedContent:
    """
    Raw scraped content before processing.

    Attributes:
        url: Source URL
        html: Raw HTML content
        status_code: HTTP status code
        headers: Response headers
        fetched_at: Timestamp when fetched
        fetch_time_ms: Time taken to fetch
    """

    url: str
    html: str
    status_code: int
    headers: Dict[str, str]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    fetch_time_ms: float = 0.0


@dataclass
class LinkScore:
    """
    Score for a discovered link.

    Attributes:
        url: Link URL
        anchor_text: Text of the anchor element
        context: Surrounding text context
        score: Calculated article probability score
        is_article: Whether likely to be an article
    """

    url: str
    anchor_text: str
    context: str
    score: float
    is_article: bool


class ContentExtractor:
    """
    Intelligent content extraction from HTML pages.

    Handles:
    - Paywall detection (returns None if content is restricted)
    - Sidebar/Related Post noise removal
    - Density-based extraction
    """

    # Priority-ordered content selectors
    CONTENT_SELECTORS = [
        '[itemprop="articleBody"]',
        '[property="articleBody"]',
        "article .content",
        "article .post-content",
        "article .entry-content",
        ".article-content",
        ".article-body",
        ".post-body",
        ".entry-content",
        ".story-body",
        "#article-content",
        "#article-body",
        # Medium Specific
        '[data-testid="postContent"]',
        'article[data-testid="postArticle"]',
        ".postArticle-content",
        "article",
        '[role="main"]',
        "main",
        ".content",
        "section",
    ]

    # Elements to remove before extraction (Expanded to trap paywalls/sidebars)
    REMOVE_SELECTORS = [
        "script",
        "style",
        "noscript",
        "iframe",
        "nav",
        "header",
        "footer",
        "aside",
        ".advertisement",
        ".ad-slot",
        ".ads",
        ".social-share",
        ".share-buttons",
        ".comments",
        ".comment-section",
        # Paywall / Sidebar / Fluff Removal
        ".related-posts",
        ".related-articles",
        ".recommended",
        ".newsletter",
        ".subscription",
        ".sidebar",
        ".widget",
        ".entry-footer",
        ".post-footer",
        ".single-related-posts",
        ".td-related-span",
        ".td-block-span",
        ".author-box",  # Often distracts from main content
        ".metabar",
        ".js-metabar",
        '[role="navigation"]',
        '[role="banner"]',
        '[role="complementary"]',
        '[role="contentinfo"]',
    ]

    @classmethod
    def extract(cls, html: str, url: str = "") -> Dict[str, Any]:
        """
        Extract article content from HTML.

        Returns None/Empty if a paywall is detected.
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. Remove unwanted elements aggressively
        for selector in cls.REMOVE_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

        # Extract metadata (usually present even in paywalled pages)
        title = cls._extract_title(soup)
        description = cls._extract_description(soup)
        author = cls._extract_author(soup)
        published = cls._extract_published_date(soup)
        image = cls._extract_image(soup, url)

        # Extract main content
        content = cls._extract_content(soup)

        # Extract keywords
        keywords = cls._extract_keywords(soup)

        # 2. PAYWALL DETECTION & VALIDATION
        # Check if the text is just a paywall teaser
        content_lower = content.lower()

        # Common paywall indicators
        paywall_indicators = [
            "subscribe to read",
            "subscribe to continue",
            "log in to continue",
            "premium content",
            "this article is for subscribers only",
        ]

        is_paywall = any(indicator in content_lower for indicator in paywall_indicators)

        # If we suspect a paywall, check the length of the *actual* content
        # If the content is very short (e.g. < 300 chars) but paywall indicators exist, reject it.
        if is_paywall and len(content) < 400:
            logger.warning(
                f"Paywall detected for {url}. Content too short to be valid article."
            )
            # Return a valid-looking dict but with empty content so Orchestrator filters it out
            # Or raise an exception. Returning empty content is safer for the current flow.
            return {
                "title": title,
                "description": description,
                "author": author,
                "published": published,
                "image": image,
                "content": "",  # Force empty content
                "keywords": keywords,
                "word_count": 0,
            }

        # 3. FALLBACK CHECK
        # If content is still too short after normal extraction, try density
        if len(content.split()) < 150:
            soup_raw = BeautifulSoup(html, "html.parser")
            fallback_content = cls._extract_content_by_density(soup_raw)

            # Recalculate paywall check on fallback
            if (
                any(
                    indicator in fallback_content.lower()
                    for indicator in paywall_indicators
                )
                and len(fallback_content) < 400
            ):
                return {
                    "title": title,
                    "description": description,
                    "author": author,
                    "published": published,
                    "image": image,
                    "content": "",
                    "keywords": keywords,
                    "word_count": 0,
                }

            if len(fallback_content.split()) > len(content.split()):
                content = fallback_content

        # 4. AGGRESSIVE FALLBACK for large HTML with little extracted content
        # If HTML is >20KB but we only got <200 words, something is wrong
        # This handles Google Cache wrapped pages and SPA content
        if len(html) > 20000 and len(content.split()) < 200:
            logger.debug(
                f"Aggressive fallback: {len(html)} chars HTML, only {len(content.split())} words extracted"
            )
            soup_fresh = BeautifulSoup(html, "html.parser")

            # Remove all noise elements
            for tag in soup_fresh(
                [
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "header",
                    "aside",
                    "noscript",
                    "iframe",
                    "svg",
                ]
            ):
                tag.decompose()

            # Get all paragraph text
            paragraphs = []
            for p in soup_fresh.find_all("p"):
                p_text = p.get_text(strip=True)
                if len(p_text) > 50:  # Only substantial paragraphs
                    paragraphs.append(p_text)

            if paragraphs:
                aggressive_content = " ".join(paragraphs)
                if len(aggressive_content.split()) > len(content.split()):
                    content = aggressive_content
                    logger.info(
                        f"Using aggressive paragraph extraction: {len(content.split())} words"
                    )

        result = {
            "title": title,
            "description": description,
            "author": author,
            "published": published,
            "image": image,
            "content": content,
            "keywords": keywords,
            "word_count": len(content.split()) if content else 0,
        }

        return result

    @classmethod
    def _extract_content(cls, soup: BeautifulSoup) -> str:
        """Extract main article text content."""
        # Try each selector in priority order
        for selector in cls.CONTENT_SELECTORS:
            content = soup.select_one(selector)
            if content:
                text = content.get_text(separator=" ", strip=True)
                # Clean up whitespace
                text = re.sub(r"\s+", " ", text)
                if len(text) > 200:  # Minimum content threshold
                    return text

        # Fallback to density-based search
        return cls._extract_content_by_density(soup)

    @classmethod
    def _extract_content_by_density(cls, soup: BeautifulSoup) -> str:
        """Find the content block with the highest density of paragraph tags."""
        # Remove scripts/styles again just in case we are looking at raw soup
        for element in soup.find_all(
            ["script", "style", "noscript", "iframe", "nav", "footer", "header"]
        ):
            element.decompose()

        candidates = soup.find_all(["div", "article", "section", "main"])
        best_candidate = None
        max_p_count = 0

        for candidate in candidates:
            # Ignore candidates that contain typical sidebar/paywall class names
            class_names = " ".join(candidate.get("class", []))
            if any(
                x in class_names
                for x in ["sidebar", "related", "footer", "meta", "comment"]
            ):
                continue

            # Skip very short candidates
            text_len = len(candidate.get_text(strip=True))
            if text_len < 200:
                continue

            p_tags = candidate.find_all("p")
            p_count = len(p_tags)

            if p_count > max_p_count:
                max_p_count = p_count
                best_candidate = candidate

        if best_candidate:
            text = best_candidate.get_text(separator=" ", strip=True)
            return re.sub(r"\s+", " ", text)

        # Final fallback to body
        body = soup.find("body")
        if body:
            text = body.get_text(separator=" ", strip=True)
            return re.sub(r"\s+", " ", text)

        return ""

    @classmethod
    def _extract_title(cls, soup: BeautifulSoup) -> str:
        """Extract article title."""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        schema_title = soup.find(itemprop="headline")
        if schema_title:
            return schema_title.get_text(strip=True)
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        if soup.title:
            return soup.title.get_text(strip=True)
        return "Untitled"

    @classmethod
    def _extract_description(cls, soup: BeautifulSoup) -> str:
        """Extract article description/summary."""
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()
        return ""

    @classmethod
    def _extract_author(cls, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author."""
        author = soup.find(itemprop="author")
        if author:
            name = author.find(itemprop="name")
            if name:
                return name.get_text(strip=True)
            return author.get_text(strip=True)
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            return meta_author["content"].strip()
        for cls_name in [".author", ".byline", ".post-author"]:
            elem = soup.select_one(cls_name)
            if elem:
                return elem.get_text(strip=True)
        return None

    @classmethod
    def _extract_published_date(cls, soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date."""
        import json

        pub_time = soup.find("meta", property="article:published_time")
        if pub_time and pub_time.get("content"):
            return pub_time["content"]
        date_pub = soup.find(itemprop="datePublished")
        if date_pub:
            return (
                date_pub.get("content")
                or date_pub.get("datetime")
                or date_pub.get_text(strip=True)
            )
        time_elem = soup.find("time", datetime=True)
        if time_elem:
            return time_elem["datetime"]
        # JSON-LD Fallback
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    date = data.get("datePublished") or data.get("dateCreated")
                    if date:
                        return date
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.debug("Failed to parse JSON-LD date script: %s", exc)
                continue
        return None

    @classmethod
    def _extract_image(cls, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract main article image."""
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return urljoin(base_url, og_image["content"])
        return None

    @classmethod
    def _extract_keywords(cls, soup: BeautifulSoup) -> List[str]:
        """Extract article keywords."""
        keywords = []
        meta_keywords = soup.find("meta", attrs={"name": "keywords"})
        if meta_keywords and meta_keywords.get("content"):
            keywords.extend(k.strip() for k in meta_keywords["content"].split(","))
        for tag in soup.find_all("meta", property="article:tag"):
            if tag.get("content"):
                keywords.append(tag["content"].strip())
        return keywords[:20]


class LinkDiscoveryAlgorithm:
    """
    Intelligent link discovery for finding article URLs.

    Uses multiple signals to score links:
    - URL patterns (article, news, post, etc.)
    - Anchor text relevance
    - Surrounding context
    - Position on page
    """

    # High-value URL patterns
    ARTICLE_PATTERNS = [
        r"/article/",
        r"/news/",
        r"/post/",
        r"/blog/",
        r"/story/",
        r"/feature/",
        r"/review/",
        r"/\d{4}/\d{2}/",  # Date patterns in URL
        r"/\d{4}/\d{2}/\d{2}/",
        r"-[a-z0-9]{6,}$",  # Slug patterns
    ]

    # Patterns to avoid
    SKIP_PATTERNS = [
        r"/tag/",
        r"/category/",
        r"/author/",
        r"/page/\d+",
        r"/search",
        r"/login",
        r"/register",
        r"/signup",
        r"/subscribe",
        r"/about",
        r"/contact",
        r"/privacy",
        r"/terms",
        r"\.(pdf|jpg|png|gif|mp4|mp3)$",
    ]

    def __init__(self, keyword_matcher: Optional[TechKeywordMatcher] = None):
        """Initialize with optional keyword matcher."""
        self._keyword_matcher = keyword_matcher or TechKeywordMatcher()
        self._article_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.ARTICLE_PATTERNS
        ]
        self._skip_patterns = [re.compile(p, re.IGNORECASE) for p in self.SKIP_PATTERNS]

    def discover_links(
        self, soup: BeautifulSoup, base_url: str, max_links: int = 50
    ) -> List[LinkScore]:
        """
        Discover and score potential article links.

        Args:
            soup: Parsed HTML
            base_url: Base URL for resolving relative links
            max_links: Maximum links to return

        Returns:
            List of LinkScore objects sorted by score
        """
        scores: List[LinkScore] = []
        seen_urls: Set[str] = set()

        for link in soup.find_all("a", href=True):
            url = urljoin(base_url, link["href"])

            # Normalize URL
            url = self._normalize_url(url)

            # Skip if already seen or invalid
            if url in seen_urls or not self._is_valid_url(url, base_url):
                continue

            seen_urls.add(url)

            # Calculate score
            score = self._score_link(link, url)
            scores.append(score)

        # Sort by score and return top links
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:max_links]

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        # Remove fragment
        parsed = urlparse(url)
        url = parsed._replace(fragment="").geturl()

        # Remove trailing slash
        return url.rstrip("/")

    def _is_valid_url(self, url: str, base_url: str) -> bool:
        """Check if URL is valid for scraping."""
        try:
            parsed = urlparse(url)
            base_parsed = urlparse(base_url)

            # Must have http(s) scheme
            if parsed.scheme not in ("http", "https"):
                return False

            # Must be from same domain or subdomain
            if not parsed.netloc.endswith(
                base_parsed.netloc.split(".")[-2]
                + "."
                + base_parsed.netloc.split(".")[-1]
            ):
                # Allow same base domain
                if parsed.netloc != base_parsed.netloc:
                    return False

            # Check skip patterns
            for pattern in self._skip_patterns:
                if pattern.search(url):
                    return False

            return True

        except Exception:
            return False

    def _score_link(self, link: Any, url: str) -> LinkScore:
        """Calculate score for a link."""
        score = 0.0

        # URL pattern matching
        for pattern in self._article_patterns:
            if pattern.search(url):
                score += 0.2

        # Anchor text analysis
        anchor_text = link.get_text(strip=True)
        if anchor_text:
            # Length bonus (longer = more likely headline)
            if 20 < len(anchor_text) < 150:
                score += 0.15

            # Tech relevance
            tech_score, _ = self._keyword_matcher.calculate_tech_score(anchor_text)
            score += tech_score * 0.3

        # Context analysis (surrounding text)
        context = ""
        parent = link.parent
        if parent:
            context = parent.get_text(strip=True)[:200]
            tech_score, _ = self._keyword_matcher.calculate_tech_score(context)
            score += tech_score * 0.15

        # Position bonus (links in article/main areas)
        if link.find_parent(["article", "main", '[role="main"]']):
            score += 0.1

        # H tag bonus (headline links)
        if link.find_parent(["h1", "h2", "h3"]):
            score += 0.1

        # Normalize score
        score = min(1.0, score)

        return LinkScore(
            url=url,
            anchor_text=anchor_text,
            context=context[:100],
            score=score,
            is_article=score > 0.3,
        )


class DeepScraper:
    """
    Advanced multi-layer deep scraping engine.

    Provides powerful web scraping capabilities:
    - Multi-layer link discovery (explores pages deeply)
    - Content quality scoring
    - Async batch processing with rate limiting
    - URL deduplication with Bloom filter
    - Response caching
    - Source reputation tracking

    NO RSS SUPPORT - Direct web scraping only for maximum control.

    Example:
        scraper = DeepScraper()

        # Scrape a source
        result = await scraper.scrape_source("https://techcrunch.com")

        # Deep analysis of single URL
        article = await scraper.analyze_url("https://example.com/article")
    """

    # User agent for requests
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        max_concurrent: int = 5,
        request_timeout: int = 15,
        rate_limit_per_domain: float = 2.0,
        cache_ttl: int = 300,
    ) -> None:
        """
        Initialize the deep scraper.

        Args:
            max_concurrent: Maximum concurrent requests
            request_timeout: Request timeout in seconds
            rate_limit_per_domain: Max requests per second per domain
            cache_ttl: Cache TTL in seconds
        """
        self._max_concurrent = max_concurrent
        self._request_timeout = request_timeout
        self._rate_limit = rate_limit_per_domain

        # Initialize components
        self._url_dedup = URLDeduplicator(expected_urls=500_000)
        self._cache = HTTPResponseCache(max_responses=500, default_ttl=cache_ttl)
        self._keyword_matcher = TechKeywordMatcher()
        self._link_discoverer = LinkDiscoveryAlgorithm(self._keyword_matcher)
        self._bypass = AntiBotBypass()
        self._content_platform_bypass = ContentPlatformBypass()

        # Initialize Advanced Bypass Components
        try:
            # Local imports to handle optional dependencies gracefully
            from src.bypass.stealth_browser_bypass import StealthBrowserBypass
            from src.extraction.api_sniffer import ApiSniffer
            from src.extraction.multi_source_reconstructor import (
                MultiSourceReconstructor,
            )
            from src.extraction.llm_content_extractor import LLMContentExtractor

            self.stealth_bypass = StealthBrowserBypass()
            self.api_sniffer = ApiSniffer()
            self.reconstructor = MultiSourceReconstructor()
            self.llm_extractor = LLMContentExtractor(use_local=True)
            logger.info(
                "Advanced bypass modules initialized (Stealth, API, Reconstructor, LLM)"
            )
        except ImportError as e:
            logger.warning(
                f"Advanced bypass modules unavailable: {e}. Running in standard mode."
            )
            self.stealth_bypass = None
            self.api_sniffer = None
            self.reconstructor = None
            self.llm_extractor = None
        except Exception as e:
            logger.warning(f"Error initializing advanced modules: {e}")
            self.stealth_bypass = None
            self.api_sniffer = None
            self.reconstructor = None
            self.llm_extractor = None

        # Rate limiting per domain
        self._domain_last_request: Dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # Statistics
        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "cached_hits": 0,
            "articles_found": 0,
        }

    async def close(self) -> None:
        """Close the scraper and release resources."""
        # Close bypass sessions to prevent resource leaks
        try:
            if hasattr(self._bypass, "close"):
                await self._bypass.close()
        except Exception as e:
            logger.debug(f"Error closing anti-bot bypass: {e}")

        try:
            if hasattr(self._content_platform_bypass, "close"):
                await self._content_platform_bypass.close()
        except Exception as e:
            logger.debug(f"Error closing content platform bypass: {e}")

        try:
            if hasattr(self, "stealth_bypass") and hasattr(
                self.stealth_bypass, "close"
            ):
                await self.stealth_bypass.close()
        except Exception as e:
            logger.debug(f"Error closing stealth bypass: {e}")

        try:
            if hasattr(self, "api_sniffer") and hasattr(self.api_sniffer, "close"):
                await self.api_sniffer.close()
        except Exception as e:
            logger.debug(f"Error closing API sniffer: {e}")

        try:
            if hasattr(self, "reconstructor") and hasattr(self.reconstructor, "close"):
                await self.reconstructor.close()
        except Exception as e:
            logger.debug(f"Error closing reconstructor: {e}")

        try:
            if hasattr(self, "llm_extractor") and hasattr(self.llm_extractor, "close"):
                await self.llm_extractor.close()
        except Exception as e:
            logger.debug(f"Error closing LLM extractor: {e}")

        # Clear caches
        self._cache._cache.clear()
        self._url_dedup = None
        logger.info("DeepScraper closed")

    async def fetch_url(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[ScrapedContent]:
        """
        Multi-tier fetch strategy:
        1. Direct fetch + validation
        2. Anti-bot bypass (Google Cache -> Archive.org)
        3. Paywall bypass (ContentPlatformBypass)
        4. Stealth browser + API interception
        5. Multi-source reconstruction
        6. LLM-assisted extraction
        """
        logger.info(f"Starting multi-tier fetch for: {url}")

        # TIER 1: Direct fetch
        # Use existing logic for direct fetch but with validation
        try:
            # We use the existing fetch_url implementation parts manually here or refactor
            # To avoid code duplication, we'll try a direct request here using the session
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=self._request_timeout)
            ) as response:
                if response.status == 200:
                    html = await response.text()
                    # Validate content
                    if self._validate_content(html, url):
                        return ScrapedContent(
                            url=url,
                            html=html,
                            status_code=200,
                            headers=dict(response.headers),
                            fetch_time_ms=0.0,
                        )
        except Exception as e:
            logger.debug(f"Tier 1 Direct fetch failed: {e}")

        # Check if URL implies binary/PDF content
        if url.lower().endswith(".pdf") or ".pdf?" in url.lower():
            logger.info(f"PDF detected by URL: {url}. Skipping browser bypass.")
            # For now, return the direct fetch result if it succeeded but we missed it above,
            # or try one more tailored fetch.
            # If Tier 1 failed, we might want to try a simple GET again specifically for PDF handling
            try:
                # Simple retry with stream=True to check headers, using proper User-Agent
                headers = {"User-Agent": self.USER_AGENT}
                async with session.get(url, timeout=10, headers=headers) as response:
                    # Check Content-Type (convert to lower case, handle potential charset)
                    content_type = response.headers.get("Content-Type", "").lower()
                    if response.status == 200 and (
                        "application/pdf" in content_type
                        or url.lower().endswith(".pdf")
                    ):
                        logger.info(f"Verified PDF content type: {content_type}")
                        return ScrapedContent(
                            url=url,
                            html="[PDF Content - Binary File]",
                            status_code=200,
                            headers=dict(response.headers),
                            fetch_time_ms=0.0,
                        )
            except Exception as pdf_error:
                logger.debug(f"PDF fetch check failed: {pdf_error}")

            # Fallback: If URL strongly indicates PDF, return placeholder to avoid crash and indicate skipped content
            if url.lower().endswith(".pdf"):
                logger.info("URL ends in .pdf, returning binary placeholder.")
                return ScrapedContent(
                    url=url,
                    html="[PDF Content - Binary File]",
                    status_code=200,
                    headers={"Content-Type": "application/pdf"},
                    fetch_time_ms=0.0,
                )

            # Returns None effectively skips to next tier, but since next tiers are bypassed for PDF...
            return None

        # TIER 2: Anti-bot bypass chain (DeepScraper internal)
        result = await self._attempt_bypass_fetch(url)
        if result and self._validate_content(result.html, url):
            return result

        # TIER 3: Paywall-specific bypass
        # Note: _content_platform_bypass is already tried in _attempt_bypass_fetch by default logic
        # But we can try it explicitly if needed or rely on _attempt_bypass_fetch
        # Given the new architecture wants explicit tiers, let's trust _attempt_bypass_fetch handles Tier 2 & 3 combined
        # OR we can explicitly separate them if _attempt_bypass_fetch didn't already

        # TIER 4: Stealth browser + API sniffing
        if self.stealth_bypass:
            content = await self._attempt_stealth_fetch(url)
            if content:
                # Stealth returns HTML or Text. If Text, wrap it.
                # Usually returns HTML.
                if not content.strip().startswith("<"):
                    content = f'<html><body><div itemprop="articleBody">{content}</div></body></html>'

                if self._validate_content(content, url):
                    return ScrapedContent(
                        url=url,
                        html=content,
                        status_code=200,
                        headers={"X-Bypass-Strategy": "stealth_browser"},
                        fetch_time_ms=0.0,
                    )

        # TIER 5: Multi-source reconstruction
        if self.reconstructor:
            content = await self._attempt_reconstruction(url)
            if content:
                # Reconstructor returns TEXT. Wrap it.
                html_wrapper = f'<html><body><div itemprop="articleBody">{content}</div></body></html>'
                if self._validate_content(html_wrapper, url):
                    return ScrapedContent(
                        url=url,
                        html=html_wrapper,
                        status_code=200,
                        headers={"X-Bypass-Strategy": "multi_source_reconstruction"},
                        fetch_time_ms=0.0,
                    )

        # FINAL TIER: LLM extraction on best available HTML
        logger.warning("All conventional methods failed, attempting LLM extraction...")
        # Need to reconstruct session for cache/archive fetch if needed,
        # but _get_best_available_html might use internal methods
        best_html = await self._get_best_available_html(url, session)
        if best_html and self.llm_extractor:
            content = self.llm_extractor.extract_with_llm(best_html, url)
            if content:
                # LLM returns TEXT. Wrap it.
                html_wrapper = f'<html><body><div itemprop="articleBody">{content}</div></body></html>'
                if self._validate_content(html_wrapper, url):
                    return ScrapedContent(
                        url=url,
                        html=html_wrapper,
                        status_code=200,
                        headers={"X-Bypass-Strategy": "llm_extraction"},
                        fetch_time_ms=0.0,
                    )

        logger.error("All multi-tier fetch attempts failed")
        return None

    async def _attempt_bypass_fetch(self, url: str) -> Optional[ScrapedContent]:
        """Attempt to fetch content using smart bypass strategies."""
        logger.info(f"🔄 Attempting smart bypass for: {url}")

        # Try ContentPlatformBypass first for known platforms (Medium, Substack, Ghost)
        try:
            platform = self._content_platform_bypass.detect_platform(url)
            if platform != ContentPlatform.UNKNOWN:
                logger.info(
                    f"📱 Detected {platform.value} platform, using ContentPlatformBypass"
                )
                result = await self._content_platform_bypass.bypass(
                    url, strategy="auto"
                )

                if result.success:
                    logger.info(
                        f"✅ Content platform bypass successful ({result.method_used}): {result.content_length} chars"
                    )
                    self._stats["successes"] += 1

                    # Cache the successful result
                    self._cache.set(
                        url,
                        200,
                        result.content,
                        {
                            "X-Bypass-Strategy": f"content_platform_{platform.value}",
                            "X-Word-Count": str(result.metadata.get("word_count", 0)),
                        },
                    )

                    return ScrapedContent(
                        url=url,
                        html=result.content,
                        status_code=200,
                        headers={
                            "X-Bypass-Strategy": f"content_platform_{platform.value}"
                        },
                        fetch_time_ms=0.0,
                    )
                else:
                    logger.warning(f"⚠️ Content platform bypass failed: {result.error}")
        except Exception as e:
            logger.warning(f"Content platform bypass error: {e}")

        # Fall back to generic AntiBotBypass
        try:
            content, strategy = await self._bypass.smart_fetch_with_fallback(url)

            if content:
                # Validate that the bypass didn't just fetch a paywall
                if self._content_platform_bypass.has_paywall(content):
                    logger.warning(
                        f"⚠️ Bypass ({strategy}) returned paywall content. Rejecting."
                    )
                    return None

                logger.info(f"✅ Bypass successful ({strategy}): {url}")
                self._stats["successes"] += 1

                # Cache the successful result
                self._cache.set(url, 200, content, {"X-Bypass-Strategy": strategy})

                return ScrapedContent(
                    url=url,
                    html=content,
                    status_code=200,
                    headers={"X-Bypass-Strategy": strategy},
                    fetch_time_ms=0.0,
                )
        except Exception as e:
            logger.error(f"Bypass failed for {url}: {e}")

        return None

    async def _attempt_stealth_fetch(self, url: str) -> Optional[str]:
        """Execute stealth browser with API interception"""
        try:
            content = await self.stealth_bypass.fetch_with_interaction(url)

            if content:
                # Check for API-sourced content from intercepted requests
                if self.api_sniffer:
                    api_content = self.api_sniffer.sniff_from_html(content)
                    if api_content:
                        return api_content

                # Extract using standard methods check?
                # No, just return content, verification happens in fetch_url
                return content

            return None

        except Exception as e:
            logger.error(f"Stealth fetch failed: {e}")
            return None

    async def _attempt_reconstruction(self, url: str) -> Optional[str]:
        """Attempt multi-source content reconstruction"""
        try:
            logger.info("Attempting multi-source reconstruction...")
            return await self.reconstructor.reconstruct(url)
        except Exception as e:
            logger.error(f"Reconstruction failed: {e}")
            return None

    async def _get_best_available_html(
        self, url: str, session: aiohttp.ClientSession
    ) -> Optional[str]:
        """Get the best HTML available from any source for LLM processing"""

        # Define sources with session needs
        async def try_cache():
            # Quick check if we have cached content (even failed/partial)
            return self._cache.get(url)

        async def try_direct():
            try:
                async with session.get(url, timeout=10) as resp:
                    return await resp.text() if resp.status == 200 else None
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.debug("Direct fetch failed for '%s': %s", url, exc)
                return None

        sources = [try_cache, try_direct]

        for source_func in sources:
            try:
                html = await source_func()
                if html and len(html) > 5000:  # Need substantial HTML
                    return html
            except Exception as exc:
                logger.debug("Source function '%s' raised: %s", source_func.__name__, exc)
                continue

        return None

    def _validate_content(self, content: str, url: str) -> bool:
        """Enhanced validation that also checks for paywall phrases"""
        if not content or len(content) < 400:
            logger.warning(f"Content too short: {len(content)} chars")
            return False

        # Check for paywall keywords
        paywall_indicators = [
            "subscribe to read",
            "sign up to read",
            "log in to continue",
            "member only",
            "premium content",
            "paywall",
        ]

        content_lower = content.lower()
        if any(indicator in content_lower for indicator in paywall_indicators):
            # Only fail if content is relatively short (avoid false positives on long articles with sticky banners)
            if len(content) < 5000:
                logger.warning("Content contains paywall indicators")
                return False

        # Also check with our robust Paywall Detector if available
        if self._content_platform_bypass.has_paywall(content):
            return False

        return True

    async def _apply_rate_limit(self, domain: str) -> None:
        """Apply per-domain rate limiting."""
        last_request = self._domain_last_request.get(domain, 0)
        min_interval = 1.0 / self._rate_limit
        elapsed = time.time() - last_request

        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self._domain_last_request[domain] = time.time()

    async def scrape_source(
        self, source_url: str, max_articles: int = 20, max_depth: int = 1
    ) -> ScrapingResult:
        """
        Scrape articles from a source website.

        Uses multi-layer link discovery to find articles.

        Args:
            source_url: Base URL of the source
            max_articles: Maximum articles to scrape
            max_depth: Maximum depth for link discovery

        Returns:
            ScrapingResult with scraped articles
        """
        logger.info(f"Scraping source: {source_url}")
        start_time = time.time()
        articles: List[Article] = []

        # Create source object
        source = Source(
            url=source_url,
            name=urlparse(source_url).netloc,
            tier=SourceTier.TIER_2,  # Default tier
            domain=urlparse(source_url).netloc,
        )

        async with aiohttp.ClientSession(
            headers={"User-Agent": self.USER_AGENT},
            connector=create_connector(),
        ) as session:
            # Fetch the main page
            content = await self.fetch_url(session, source_url)

            if not content:
                return ScrapingResult(
                    status=ScrapingStatus.FAILED,
                    articles=tuple(),
                    source=source,
                    duration_ms=(time.time() - start_time) * 1000,
                    error_message="Failed to fetch source page",
                )

            # Discover article links
            soup = BeautifulSoup(content.html, "html.parser")
            links = self._link_discoverer.discover_links(
                soup, source_url, max_links=max_articles * 2
            )

            # Filter to likely articles
            article_urls = [
                link.url
                for link in links
                if link.is_article and not self._url_dedup.is_duplicate(link.url)
            ][:max_articles]

            # Fetch and process articles concurrently
            tasks = [
                self._process_article_url(session, url, source) for url in article_urls
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Article):
                    articles.append(result)
                    self._url_dedup.add(result.url)
                    self._stats["articles_found"] += 1

        duration_ms = (time.time() - start_time) * 1000

        if articles:
            logger.info(
                f"✓ Scraped {len(articles)} articles from {source_url} "
                f"in {duration_ms:.0f}ms"
            )
            return ScrapingResult(
                status=ScrapingStatus.SUCCESS,
                articles=tuple(articles),
                source=source,
                duration_ms=duration_ms,
            )
        else:
            return ScrapingResult(
                status=ScrapingStatus.PARTIAL,
                articles=tuple(),
                source=source,
                duration_ms=duration_ms,
                error_message="No articles found",
            )

    async def _process_article_url(
        self, session: aiohttp.ClientSession, url: str, source: Source
    ) -> Optional[Article]:
        """Process a single article URL."""
        try:
            content = await self.fetch_url(session, url)

            if not content:
                return None

            # Extract content
            extracted = ContentExtractor.extract(content.html, url)

            # Check minimum content
            if extracted["word_count"] < 100:
                return None

            # Calculate tech score
            tech_score, keywords = self._keyword_matcher.calculate_tech_score(
                extracted["content"]
            )

            # Skip non-tech content
            if tech_score < 0.2:
                return None

            # Generate ID
            article_id = hashlib.md5(url.encode()).hexdigest()

            # Create article
            return Article(
                id=article_id,
                url=url,
                title=extracted["title"],
                content=extracted["content"],
                summary=extracted["description"] or "",
                source=source.name,
                source_tier=source.tier,
                published_at=self._parse_date(extracted["published"]),
                tech_score=TechScore(
                    score=tech_score,
                    confidence=0.8,
                    matched_keywords=tuple(keywords),
                ),
                keywords=tuple(extracted["keywords"]),
            )

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            return None

    def _parse_date(
        self, date_str: Optional[str], url: Optional[str] = None
    ) -> Optional[datetime]:
        """
        Parse date string with comprehensive format support.

        Supports 20+ formats including:
        - ISO 8601: 2025-01-12T09:30:00Z
        - RFC 2822: Sun, 12 Jan 2025 09:30:00 +0000
        - Relative: "2 hours ago", "yesterday"
        - Human: "January 12, 2025", "12/01/2025"
        - URL patterns: /2025/01/12/
        """
        import re
        from datetime import timedelta

        if not date_str:
            # Try URL-based extraction
            if url:
                return self._parse_date_from_url(url)
            return None

        # Clean the string
        date_str = date_str.strip()

        # Try relative time first
        result = self._parse_relative_time(date_str)
        if result:
            return result

        # Try common datetime formats
        datetime_formats = [
            # ISO 8601 variants
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            # Date only
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            # Human readable
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d, %Y at %I:%M %p",
            # RFC 2822
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            # Other common
            "%Y%m%d",
            "%d-%m-%Y",
        ]

        for fmt in datetime_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except ValueError:
                continue

        # Try dateutil as fallback
        try:
            from dateutil import parser as dateutil_parser

            dt = dateutil_parser.parse(date_str, fuzzy=True)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, OverflowError, ImportError) as exc:
            logger.debug("dateutil could not parse date string '%s': %s", date_str, exc)

        # Try URL as last resort
        if url:
            return self._parse_date_from_url(url)

        return None

    def _parse_relative_time(self, date_str: str) -> Optional[datetime]:
        """Parse relative time expressions like '2 hours ago'."""
        import re
        from datetime import timedelta

        date_lower = date_str.lower()
        now = datetime.now(UTC)

        patterns = [
            (r"(\d+)\s*(?:second|sec)s?\s*ago", "seconds"),
            (r"(\d+)\s*(?:minute|min)s?\s*ago", "minutes"),
            (r"(\d+)\s*(?:hour|hr)s?\s*ago", "hours"),
            (r"(\d+)\s*days?\s*ago", "days"),
            (r"(\d+)\s*weeks?\s*ago", "weeks"),
            (r"(\d+)\s*months?\s*ago", "months"),
        ]

        for pattern, unit in patterns:
            match = re.search(pattern, date_lower, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                if unit == "seconds":
                    return now - timedelta(seconds=value)
                elif unit == "minutes":
                    return now - timedelta(minutes=value)
                elif unit == "hours":
                    return now - timedelta(hours=value)
                elif unit == "days":
                    return now - timedelta(days=value)
                elif unit == "weeks":
                    return now - timedelta(weeks=value)
                elif unit == "months":
                    return now - timedelta(days=value * 30)

        if "yesterday" in date_lower:
            return now - timedelta(days=1)
        if "today" in date_lower:
            return now
        if "just now" in date_lower or "moment" in date_lower:
            return now

        return None

    def _parse_date_from_url(self, url: str) -> Optional[datetime]:
        """Extract date from URL path like /2025/01/12/."""
        import re

        match = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
        if match:
            try:
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError as exc:
                logger.debug("Invalid date components in URL '%s': %s", url, exc)
        return None

    async def analyze_url_deep(self, url: str) -> Optional[Article]:
        """
        Perform deep analysis of a specific URL.

        Extracts comprehensive information and generates
        AI-enhanced summary.

        Args:
            url: URL to analyze

        Returns:
            Detailed Article object or None if failed
        """
        logger.info(f"Deep analysis: {url}")

        async with aiohttp.ClientSession(
            headers={"User-Agent": self.USER_AGENT},
            connector=create_connector(),
        ) as session:
            return await self._process_article_url(
                session,
                url,
                Source(
                    url=url,
                    name="User Provided",
                    tier=SourceTier.TIER_2,
                    domain=urlparse(url).netloc,
                ),
            )

    def analyze_from_html(self, url: str, html: str) -> Optional[Article]:
        """
        Analyze pre-fetched HTML content without making a network request.

        This is used when content has already been fetched via bypass methods.

        Args:
            url: Original URL of the content
            html: Pre-fetched HTML content

        Returns:
            Article object or None if processing failed
        """
        logger.info(f"Analyzing pre-fetched content from: {url}")

        try:
            # Extract content from HTML
            extracted = ContentExtractor.extract(html, url)

            # Log extraction results for debugging
            word_count = extracted.get("word_count", 0)
            title = extracted.get("title", "No title")
            logger.info(
                f"📊 Extracted: {word_count} words, title='{title[:50]}...' from {url}"
            )

            # Check minimum content (lowered threshold for cached pages)
            if word_count < 50:
                logger.warning(f"Content too short ({word_count} words) from {url}")
                return None

            # Calculate tech score
            tech_score, keywords = self._keyword_matcher.calculate_tech_score(
                extracted["content"]
            )

            # Generate ID
            article_id = hashlib.md5(url.encode()).hexdigest()

            # Create article
            return Article(
                id=article_id,
                url=url,
                title=extracted["title"],
                content=extracted["content"],
                summary=extracted["description"] or "",
                source="User Provided (Bypassed)",
                source_tier=SourceTier.TIER_2,
                published_at=self._parse_date(extracted["published"]),
                tech_score=TechScore(
                    score=tech_score,
                    confidence=0.8,
                    matched_keywords=tuple(keywords),
                ),
                keywords=tuple(extracted["keywords"]),
            )

        except Exception as e:
            logger.error(f"Error analyzing pre-fetched content from {url}: {e}")
            return None

    @property
    def stats(self) -> Dict[str, Any]:
        """Get scraping statistics."""
        return {
            **self._stats,
            "cache_stats": self._cache.stats,
            "dedup_stats": self._url_dedup.stats,
        }

    def reset_stats(self) -> None:
        """Reset all statistics."""
        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "cached_hits": 0,
            "articles_found": 0,
        }
