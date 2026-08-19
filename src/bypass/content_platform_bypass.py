"""
Universal Content Platform Paywall Bypass Module.

Provides specialized bypass handlers for content delivery platforms:
- Medium.com (and Medium-powered sites)
- Substack
- Ghost CMS
- Hashnode
- DEV.to
- Beehiiv
- Buttondown

These platforms typically use client-side paywall enforcement with:
1. Overlay/modal blocking elements
2. Content blur/fade effects
3. Scroll locking
4. Metered access (cookie-based)

This module provides both Playwright-based (JavaScript injection) and 
HTTP-only (header manipulation) bypass strategies.
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from src.bypass.stealth import StealthConfig, get_stealth_headers

logger = logging.getLogger(__name__)


class ContentPlatform(Enum):
    """Supported content delivery platforms."""
    MEDIUM = "medium"
    SUBSTACK = "substack"
    GHOST = "ghost"
    HASHNODE = "hashnode"
    DEV_TO = "dev.to"
    BEEHIIV = "beehiiv"
    BUTTONDOWN = "buttondown"
    WORDPRESS_PREMIUM = "wordpress_premium"
    GENERIC_PAYWALL = "generic_paywall"  # Wired, NYT, Ars, WSJ, etc.
    UNKNOWN = "unknown"


@dataclass
class PlatformBypassResult:
    """Result of a content platform bypass attempt."""
    success: bool
    content: str
    platform: ContentPlatform
    method_used: str
    bypass_time_ms: float = 0.0
    content_length: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for bypass attempts."""
    max_requests_per_minute: int = 10
    max_requests_per_hour: int = 60
    backoff_multiplier: float = 2.0
    initial_delay_ms: float = 500.0
    max_delay_ms: float = 30000.0


# Platform-specific selectors for paywall overlay detection and removal
PLATFORM_SELECTORS: Dict[ContentPlatform, Dict[str, List[str]]] = {
    ContentPlatform.MEDIUM: {
        "overlays": [
            'div[data-testid="paywall-overlay"]',
            'div[aria-label="Paywall"]',
            '.paywall-overlay',
            '.meteredContent',
            '.meteredFooter',
            '.metVis',
            'div[class*="meteredContent"]',
            'div[class*="paywall"]',
            '.overlay--gradient',
            '.js-postShareIcons',  # Sometimes used in paywall flows
        ],
        "blur_targets": [
            '.metVis',
            '.meteredFooter',
            'div[class*="blur"]',
            'section[class*="locked"]',
        ],
        "scroll_blockers": [
            'body[style*="overflow: hidden"]',
            'html[style*="overflow: hidden"]',
        ],
        "content_markers": [
            'article',
            '.postArticle-content',
            'section[data-field="body"]',
            '.section-inner',
        ],
    },
    ContentPlatform.SUBSTACK: {
        "overlays": [
            '.paywall-modal',
            '.paywall',
            '.subscribe-modal',
            '.subscription-modal',
            'div[class*="paywall"]',
            '.paywall-cta',
            '.locked-content',
            '.PaidOnlyContent',
            '.paywall-bar',
        ],
        "blur_targets": [
            '.blurred-content',
            'div[class*="blur"]',
            '.fade-out-content',
        ],
        "scroll_blockers": [],
        "content_markers": [
            '.post-content',
            '.body',
            'article',
            '.available-content',
        ],
    },
    ContentPlatform.GHOST: {
        "overlays": [
            '.gh-paywall',
            '.subscribe-overlay',
            '.members-only-cta',
            '.kg-signup-card',
        ],
        "blur_targets": [
            '.members-only-blur',
        ],
        "scroll_blockers": [],
        "content_markers": [
            '.gh-content',
            '.post-content',
            'article',
        ],
    },
    ContentPlatform.HASHNODE: {
        "overlays": [
            '.paywall-overlay',
            '.premium-modal',
        ],
        "blur_targets": [],
        "scroll_blockers": [],
        "content_markers": [
            '.blog-content',
            'article',
        ],
    },
    ContentPlatform.DEV_TO: {
        "overlays": [],  # DEV.to is mostly free
        "blur_targets": [],
        "scroll_blockers": [],
        "content_markers": [
            '.crayons-article__main',
            'article',
        ],
    },
    ContentPlatform.GENERIC_PAYWALL: {
        "overlays": [
            # Common paywall patterns
            '.paywall-overlay',
            '.paywall',
            '.subscriber-only',
            '[class*="paywall"]',
            '[class*="subscribe-modal"]',
            '.paid-content-overlay',
            '.metered-content-blocker',
            # Site-specific patterns
            '.c-regwall-container',  # Wired
            '.persistent-bottom-container',  # Wired
            '.paywall-bar',
            '.pianoPaywall',  # Piano paywall service
        ],
        "blur_targets": [
            '[class*="blur"]',
            '.truncated-content',
            '.fade-out-content',
        ],
        "scroll_blockers": [
            'body[style*="overflow: hidden"]',
            'html[style*="overflow: hidden"]',
        ],
        "content_markers": [
            'article',
            '.article-body',
            '.article-content',
            '.story-body',
            '.post-content',
            '[itemprop="articleBody"]',
            'main',
        ],
    },
}

# Detection patterns for identifying platforms from HTML/URL
PLATFORM_DETECTION_PATTERNS: Dict[ContentPlatform, Dict[str, List[str]]] = {
    ContentPlatform.MEDIUM: {
        "url_patterns": [
            r"medium\.com",
            r"\.medium\.com",
            r"towardsdatascience\.com",
            r"betterprogramming\.pub",
            r"levelup\.gitconnected\.com",
            r"gitconnected\.com",
        ],
        "html_patterns": [
            r"<meta[^>]+Medium[^>]*>",
            r"data-is-preview-mode",
            r"_APOLLO_STATE_",
            r"medium\.com/_/fp",
        ],
    },
    ContentPlatform.SUBSTACK: {
        "url_patterns": [
            r"\.substack\.com",
            r"substack\.com",
        ],
        "html_patterns": [
            r"substack-headless",
            r"Substack",
            r"data-newsletter",
        ],
    },
    ContentPlatform.GHOST: {
        "url_patterns": [],  # Ghost is self-hosted, hard to detect by URL
        "html_patterns": [
            r"ghost\-portal",
            r"<meta[^>]+ghost-[^>]*>",
            r"data-members-signin",
        ],
    },
    ContentPlatform.GENERIC_PAYWALL: {
        "url_patterns": [
            # ONLY include sites with HARD PAYWALLS (almost all content paywalled)
            # Major newspapers with strict paywalls
            r"nytimes\.com",
            r"wsj\.com",
            r"washingtonpost\.com",
            r"ft\.com",
            r"theatlantic\.com",
            r"newyorker\.com",
            r"economist\.com",
            r"bloomberg\.com",
            # NOTE: Remove tech sites - they have metered/soft paywalls or are free
            # These should only trigger bypass if actual paywall HTML is detected:
            # - wired.com, arstechnica.com, technologyreview.com, theverge.com
            # - zdnet.com, venturebeat.com, cnet.com, businessinsider.com, forbes.com
        ],
        "html_patterns": [
            r"paywall",
            r"subscriber.?only",
            r"metered.?content",
        ],
    },
}

# Paywall indicator patterns (text-based detection)
PAYWALL_INDICATORS: List[str] = [
    r"member[- ]?only",
    r"subscribe to (continue|read|unlock)",
    r"subscribe or log ?in to (continue|read|unlock)",
    r"this (story|article|post) is (for )?premium members",
    r"free article[s]? remaining",
    r"unlock (this|full) (story|article)",
    r"become a member",
    r"create an account to read",
    r"upgrade your account",
    r"get unlimited access",
    r"read the full story",
    r"you've hit the limit",
    r"free preview",
]


class ContentPlatformBypass:
    """
    Universal bypass handler for content delivery platforms.
    
    Provides multiple strategies for bypassing soft paywalls on platforms
    like Medium, Substack, Ghost, etc.
    
    Features:
    - Platform auto-detection
    - Playwright-first JavaScript injection
    - HTTP fallback with stealth headers
    - Rate limiting protection
    - Exponential backoff on failures
    
    Example:
        bypass = ContentPlatformBypass()
        result = await bypass.bypass(
            "https://medium.com/article/example",
            strategy="playwright"
        )
        if result.success:
            print(result.content)
    """
    
    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        stealth_config: Optional[StealthConfig] = None,
        timeout: int = 30,
    ):
        """
        Initialize content platform bypass handler.
        
        Args:
            rate_limit_config: Rate limiting settings.
            stealth_config: Stealth configuration for requests.
            timeout: Request timeout in seconds.
        """
        self.rate_limit = rate_limit_config or RateLimitConfig()
        self.stealth_config = stealth_config or StealthConfig()
        self.timeout = timeout
        
        # Rate limiting state
        self._request_times: List[datetime] = []
        self._failure_count: int = 0
        self._last_failure_time: Optional[datetime] = None
        
        # Session management
        self._session: Optional[aiohttp.ClientSession] = None
        self._browser = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.stealth_config.get_aiohttp_headers(),
                cookie_jar=aiohttp.DummyCookieJar(),  # Fresh session
            )
        return self._session
    
    async def close(self) -> None:
        """Close the session and stealth browser."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            
        if getattr(self, '_browser', None) is not None:
            try:
                await self._browser.close()
            except Exception as e:
                logger.debug(f"Error closing browser in ContentPlatformBypass: {e}")
            self._browser = None
    
    async def __aenter__(self) -> "ContentPlatformBypass":
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.close()
    
    def detect_platform(self, url: str, html: Optional[str] = None) -> ContentPlatform:
        """
        Detect which content platform a URL belongs to.
        
        Args:
            url: URL to analyze.
            html: Optional HTML content for pattern matching.
        
        Returns:
            Detected ContentPlatform.
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        for platform, patterns in PLATFORM_DETECTION_PATTERNS.items():
            # Check URL patterns
            for pattern in patterns.get("url_patterns", []):
                if re.search(pattern, domain, re.IGNORECASE):
                    return platform
            
            # Check HTML patterns if available
            if html:
                for pattern in patterns.get("html_patterns", []):
                    if re.search(pattern, html, re.IGNORECASE):
                        return platform
        
        return ContentPlatform.UNKNOWN
    
    def has_paywall(self, html: str) -> bool:
        """
        Check if HTML content shows signs of paywall.
        
        Note: This is a simple heuristic. For better accuracy, use 
        is_content_accessible() which also checks for actual article content.
        
        Args:
            html: HTML content to analyze.
        
        Returns:
            True if paywall indicators found.
        """
        html_lower = html.lower()
        
        for pattern in PAYWALL_INDICATORS:
            if re.search(pattern, html_lower, re.IGNORECASE):
                return True
        
        return False
    
    def is_content_accessible(self, html: str, platform: ContentPlatform) -> Tuple[bool, int]:
        """
        Check if the actual article content is accessible.
        
        This is smarter than has_paywall() - it extracts the article
        body and validates it has substantial content, even if the page
        contains some paywall-related promotional text.
        
        Enhanced for SPAs like Medium that use React/client-side rendering.
        
        Args:
            html: HTML content to analyze.
            platform: The platform type for selector hints.
        
        Returns:
            Tuple of (is_accessible, content_word_count)
        """
        try:
            from bs4 import BeautifulSoup
            import json
            
            soup = BeautifulSoup(html, "html.parser")
            
            # Strategy 0: Try extracting from JSON-LD (most reliable for SPAs)
            best_text = ""
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '{}')
                    # Handle array of items
                    if isinstance(data, list):
                        data = data[0] if data else {}
                    
                    # Extract articleBody if available (present in proper schema.org markup)
                    article_body = data.get('articleBody', '')
                    if article_body and len(article_body.split()) > len(best_text.split()):
                        best_text = article_body
                    
                    # Try getting description as fallback
                    desc = data.get('description', '')
                    if desc and len(desc.split()) > len(best_text.split()):
                        best_text = desc
                except (json.JSONDecodeError, TypeError, AttributeError):
                    continue
            
            # Remove script, style, and nav elements to get cleaner text
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'svg']):
                tag.decompose()
            
            # Strategy 1: Try platform-specific content markers
            selectors = PLATFORM_SELECTORS.get(platform, PLATFORM_SELECTORS[ContentPlatform.MEDIUM])
            content_markers = selectors.get("content_markers", ["article"])
            
            for selector in content_markers:
                elements = soup.select(selector)
                for el in elements:
                    text = el.get_text(separator=" ", strip=True)
                    if len(text.split()) > len(best_text.split()):
                        best_text = text
            
            # Strategy 2: Medium-specific paragraph extraction
            if platform == ContentPlatform.MEDIUM and len(best_text.split()) < 200:
                # Medium renders content as <p> tags in specific sections
                paragraphs = []
                for p in soup.find_all('p'):
                    # Skip short paragraphs (buttons, captions)
                    p_text = p.get_text(separator=" ", strip=True)
                    if len(p_text) > 80:  # Real content paragraphs are longer
                        paragraphs.append(p_text)
                
                combined = " ".join(paragraphs)
                if len(combined.split()) > len(best_text.split()):
                    best_text = combined
            
            # Strategy 3: Find any element with substantial text (more aggressive)
            if len(best_text.split()) < 200:
                for tag in soup.find_all(['article', 'main', 'div', 'section']):
                    # Skip if it's likely navigation or sidebar
                    cls = " ".join(tag.get('class', [])).lower()
                    tag_id = (tag.get('id') or '').lower()
                    
                    skip_patterns = ['nav', 'menu', 'sidebar', 'footer', 'header', 'comment', 
                                     'recommend', 'related', 'share', 'social', 'subscription']
                    if any(skip in cls or skip in tag_id for skip in skip_patterns):
                        continue
                    
                    text = tag.get_text(separator=" ", strip=True)
                    words = text.split()
                    
                    # If this element has more words than our best, use it
                    if len(words) > len(best_text.split()):
                        best_text = text
            
            # Strategy 4: If still not enough, just get all body text
            if len(best_text.split()) < 200:
                body = soup.find('body')
                if body:
                    best_text = body.get_text(separator=" ", strip=True)
            
            # Calculate word count
            words = best_text.split()
            word_count = len(words)
            
            # Check for hard paywall indicators that usually mean truncation
            # false positives on word count often happen because of "read more", "sign up", "recommended" sections
            paywall_phrases = [
                "Sign up to read the full story",
                "The author made this story available to Medium members only",
                "Create an account to read the full story",
                "Upgrade your account to read",
                "Subscribe or log in to Continue Reading",
                "Subscribe to read",
                "Get one year subscription for",
            ]
            
            has_hard_paywall = False
            for phrase in paywall_phrases:
                if phrase.lower() in best_text.lower():
                    # Only consider it a hard paywall if content is relatively short (< 1000 words)
                    # If we have a massive article (1000+ words), it might just be the footer CTA
                    if word_count < 1000:
                        has_hard_paywall = True
                        logger.warning(f"Detected hard paywall phrase: '{phrase}'")
                        break
            
            # Consider content accessible if we have substantial text AND no hard blocking paywall
            # Lowered threshold for SPAs that may have partial content
            MIN_WORDS_FOR_SUCCESS = 150
            
            is_accessible = (word_count >= MIN_WORDS_FOR_SUCCESS) and (not has_hard_paywall)
            
            logger.debug(f"Content check: {word_count} words, accessible={is_accessible}, paywall_detected={has_hard_paywall}")
            
            return is_accessible, word_count
            
        except Exception as e:
            logger.warning(f"Content accessibility check failed: {e}")
            # Fall back to simple length check
            return len(html) > 5000, len(html) // 5
    
    async def _check_rate_limit(self) -> Optional[float]:
        """
        Check rate limit and return delay if needed.
        
        Returns:
            Delay in seconds if rate limited, None otherwise.
        """
        now = datetime.now(timezone.utc)
        
        # Clean old request times
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        
        self._request_times = [
            t for t in self._request_times if t > hour_ago
        ]
        
        # Count recent requests
        requests_last_minute = sum(
            1 for t in self._request_times if t > minute_ago
        )
        requests_last_hour = len(self._request_times)
        
        # Check limits
        if requests_last_minute >= self.rate_limit.max_requests_per_minute:
            delay = 60.0
            logger.warning(f"Rate limit hit (minute), waiting {delay}s")
            return delay
        
        if requests_last_hour >= self.rate_limit.max_requests_per_hour:
            delay = 3600.0
            logger.warning(f"Rate limit hit (hour), waiting {delay}s")
            return delay
        
        # Check for backoff after failures
        if self._failure_count > 0 and self._last_failure_time:
            backoff_delay = min(
                self.rate_limit.initial_delay_ms * (
                    self.rate_limit.backoff_multiplier ** self._failure_count
                ),
                self.rate_limit.max_delay_ms
            ) / 1000.0
            
            time_since_failure = (now - self._last_failure_time).total_seconds()
            if time_since_failure < backoff_delay:
                remaining = backoff_delay - time_since_failure
                logger.debug(f"Backoff active, waiting {remaining:.1f}s")
                return remaining
        
        return None
    
    def _record_request(self, success: bool) -> None:
        """Record a request for rate limiting."""
        now = datetime.now(timezone.utc)
        self._request_times.append(now)
        
        if success:
            self._failure_count = 0
            self._last_failure_time = None
        else:
            self._failure_count += 1
            self._last_failure_time = now
    
    async def bypass(
        self,
        url: str,
        strategy: str = "auto",
        platform: Optional[ContentPlatform] = None,
    ) -> PlatformBypassResult:
        """
        Bypass paywall on a content platform URL.
        
        Args:
            url: URL to access.
            strategy: "playwright", "http", or "auto" (playwright first).
            platform: Optional platform hint (auto-detected if None).
        
        Returns:
            PlatformBypassResult with content and metadata.
        """
        start_time = datetime.now(timezone.utc)
        
        # Check rate limit
        delay = await self._check_rate_limit()
        if delay:
            await asyncio.sleep(delay)
        
        # Detect platform if not provided
        if platform is None:
            platform = self.detect_platform(url)
        
        logger.info(f"Bypassing {platform.value} paywall for: {url}")
        
        # Strategy selection
        strategies = []
        if strategy == "auto":
            strategies = ["playwright", "http"]
        elif strategy == "playwright":
            strategies = ["playwright"]
        elif strategy == "http":
            strategies = ["http"]
        else:
            strategies = [strategy]
        
        last_error = None
        
        for strat in strategies:
            try:
                if strat == "playwright":
                    result = await self._playwright_bypass(url, platform)
                else:
                    result = await self._http_bypass(url, platform)
                
                if result.success:
                    self._record_request(True)
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                    result.bypass_time_ms = elapsed
                    return result
                
                last_error = result.error
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Strategy {strat} failed: {e}")
        
        # All strategies failed
        self._record_request(False)
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
        return PlatformBypassResult(
            success=False,
            content="",
            platform=platform,
            method_used=strategy,
            bypass_time_ms=elapsed,
            error=last_error or "All bypass strategies failed",
        )
    
    async def _get_browser(self):
        """Get or initialize the stealth browser."""
        if getattr(self, '_browser', None) is None:
            from src.bypass.browser_engine import StealthBrowser
            self._browser = StealthBrowser(headless=True)
            await self._browser.initialize()
        return self._browser

    async def _playwright_bypass(
        self,
        url: str,
        platform: ContentPlatform
    ) -> PlatformBypassResult:
        """
        Bypass using Playwright with Neural DOM Eraser.
        
        Args:
            url: URL to access.
            platform: Detected platform.
        
        Returns:
            PlatformBypassResult.
        """
        try:
            browser = await self._get_browser()
            
            # Create page
            page = await browser.new_page()
            
            try:
                # Navigate
                await page.goto(url, wait_until="networkidle", timeout=30000)
                
                # Wait for article content to load (important for JS-heavy sites)
                try:
                    await page.wait_for_selector('article', timeout=10000)
                except Exception:
                    pass  # Continue even if no article tag found
                
                # Additional wait for JS frameworks to complete rendering
                await asyncio.sleep(2)
                
                # Inject platform-specific eraser
                await self._inject_platform_eraser(page, platform)
                
                # Get content
                content = await page.content()
                
                # Validate using content accessibility check (smarter than has_paywall)
                is_accessible, word_count = self.is_content_accessible(content, platform)
                
                if is_accessible:
                    return PlatformBypassResult(
                        success=True,
                        content=content,
                        platform=platform,
                        method_used="playwright",
                        content_length=len(content),
                        metadata={"word_count": word_count},
                    )
                else:
                    return PlatformBypassResult(
                        success=False,
                        content=content,
                        platform=platform,
                        method_used="playwright",
                        content_length=len(content),
                        error=f"Insufficient article content (only {word_count} words found)",
                    )
                
            finally:
                await page.close()
                
                
        except ImportError:
            return PlatformBypassResult(
                success=False,
                content="",
                platform=platform,
                method_used="playwright",
                error="Playwright not installed",
            )
        except Exception as e:
            return PlatformBypassResult(
                success=False,
                content="",
                platform=platform,
                method_used="playwright",
                error=str(e),
            )
    
    async def _inject_platform_eraser(self, page: Any, platform: ContentPlatform) -> None:
        """
        Inject platform-specific DOM eraser script.
        
        Args:
            page: Playwright page.
            platform: Detected platform.
        """
        selectors = PLATFORM_SELECTORS.get(platform, PLATFORM_SELECTORS[ContentPlatform.MEDIUM])
        
        # Build the comprehensive eraser script
        eraser_script = """
        (selectors) => {
            const log = (msg) => console.log('[ContentPlatformEraser] ' + msg);
            
            // ===== 1. OVERLAY REMOVAL =====
            selectors.overlays.forEach(sel => {
                try {
                    document.querySelectorAll(sel).forEach(el => {
                        log('Removing overlay: ' + sel);
                        el.remove();
                    });
                } catch(e) {}
            });
            
            // ===== 2. HEURISTIC BLOCKER DETECTION =====
            const KEYWORDS = ['subscribe', 'member', 'unlock', 'premium', 'paywall', 
                              'upgrade', 'join', 'sign up', 'sign in', 'login',
                              'free articles', 'limit reached'];
            const HIGH_Z_INDEX = 10;
            const COVERAGE_THRESHOLD = 0.2;
            
            function getCoverage(el) {
                try {
                    const rect = el.getBoundingClientRect();
                    const viewArea = window.innerWidth * window.innerHeight;
                    if (viewArea === 0) return 0;
                    
                    const visLeft = Math.max(0, rect.left);
                    const visRight = Math.min(window.innerWidth, rect.right);
                    const visTop = Math.max(0, rect.top);
                    const visBottom = Math.min(window.innerHeight, rect.bottom);
                    
                    if (visLeft < visRight && visTop < visBottom) {
                        return ((visRight - visLeft) * (visBottom - visTop)) / viewArea;
                    }
                } catch(e) {}
                return 0;
            }
            
            function hasBlockingKeywords(el) {
                const text = (el.innerText || '').toLowerCase();
                if (text.length > 1000 || text.length < 5) return false;
                return KEYWORDS.some(kw => text.includes(kw));
            }
            
            // Find and remove blockers
            document.querySelectorAll('div, section, aside, footer, dialog, [role="dialog"]').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return;
                
                const isOverlay = ['fixed', 'absolute', 'sticky'].includes(style.position);
                const zIndex = parseInt(style.zIndex, 10) || 0;
                const coverage = getCoverage(el);
                const hasKeywords = hasBlockingKeywords(el);
                
                if (isOverlay && zIndex >= HIGH_Z_INDEX) {
                    if (coverage > COVERAGE_THRESHOLD || (coverage > 0.05 && hasKeywords)) {
                        log(`Heuristic removal: z=${zIndex}, coverage=${(coverage*100).toFixed(1)}%`);
                        el.remove();
                    }
                }
            });
            
            // ===== 3. BLUR REMOVAL =====
            selectors.blur_targets.forEach(sel => {
                try {
                    document.querySelectorAll(sel).forEach(el => {
                        el.style.filter = 'none';
                        el.style.opacity = '1';
                    });
                } catch(e) {}
            });
            
            // Global blur scrub
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.filter.includes('blur')) {
                    el.style.filter = 'none';
                }
            });
            
            // ===== 4. SCROLL RESTORATION =====
            document.body.style.overflow = 'visible';
            document.body.style.overflowY = 'auto';
            document.body.style.position = 'static';
            document.documentElement.style.overflow = 'visible';
            document.documentElement.style.overflowY = 'auto';
            
            // ===== 5. INTERACTIVITY RESTORATION =====
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.userSelect === 'none') {
                    el.style.userSelect = 'text';
                }
                if (style.pointerEvents === 'none') {
                    // Only restore if it's content, not decorative
                    if (el.innerText && el.innerText.length > 20) {
                        el.style.pointerEvents = 'auto';
                    }
                }
            });
            
            // ===== 6. CONTENT REHYDRATION =====
            selectors.content_markers.forEach(sel => {
                try {
                    document.querySelectorAll(sel).forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none') {
                            el.style.display = 'block';
                        }
                        if (style.visibility === 'hidden') {
                            el.style.visibility = 'visible';
                        }
                        // Remove height restrictions
                        if (el.style.maxHeight) {
                            el.style.maxHeight = 'none';
                        }
                    });
                } catch(e) {}
            });
            
            log('Eraser complete');
        }
        """
        
        try:
            await page.evaluate(eraser_script, dict(selectors))
            logger.info(f"Injected {platform.value} eraser script")
            
            # Wait for layout to settle
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.warning(f"Eraser injection failed: {e}")
    
    async def _http_bypass(
        self,
        url: str,
        platform: ContentPlatform
    ) -> PlatformBypassResult:
        """
        Bypass using HTTP requests with stealth headers.
        
        Uses referer spoofing and archive fallbacks.
        
        Args:
            url: URL to access.
            platform: Detected platform.
        
        Returns:
            PlatformBypassResult.
        """
        session = await self._get_session()
        
        # Strategy 1: Google referer spoof
        referers = [
            "https://www.google.com/",
            "https://news.google.com/",
            "https://t.co/",           # Twitter
            "https://l.facebook.com/",
        ]
        
        for referer in referers:
            try:
                headers = get_stealth_headers(
                    referer=referer,
                    custom_headers={"Sec-Fetch-Site": "cross-site"}
                )
                
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    if response.status == 200:
                        content = await response.text()
                        
                        is_accessible, word_count = self.is_content_accessible(content, platform)
                        if is_accessible:
                            return PlatformBypassResult(
                                success=True,
                                content=content,
                                platform=platform,
                                method_used=f"http_referer_{referer.split('/')[2]}",
                                content_length=len(content),
                                metadata={"word_count": word_count},
                            )
                            
            except Exception as e:
                logger.debug(f"Referer {referer} failed: {e}")
        
        # Strategy 2: Archive fallback
        archive_urls = [
            f"https://web.archive.org/web/2/{url}",
            f"https://archive.is/newest/{url}",
        ]
        
        for archive_url in archive_urls:
            try:
                async with session.get(
                    archive_url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=True,
                ) as response:
                    if response.status == 200:
                        content = await response.text()
                        if len(content) > 1000:
                            return PlatformBypassResult(
                                success=True,
                                content=content,
                                platform=platform,
                                method_used="http_archive",
                                content_length=len(content),
                                metadata={"archive_url": archive_url},
                            )
            except Exception as e:
                logger.debug(f"Archive {archive_url} failed: {e}")
        
        return PlatformBypassResult(
            success=False,
            content="",
            platform=platform,
            method_used="http",
            error="All HTTP strategies failed",
        )


# Convenience functions
async def bypass_content_platform(
    url: str,
    strategy: str = "auto"
) -> PlatformBypassResult:
    """
    Convenience function to bypass content platform paywall.
    
    Args:
        url: URL to access.
        strategy: "playwright", "http", or "auto".
    
    Returns:
        PlatformBypassResult.
    """
    async with ContentPlatformBypass() as bypass:
        return await bypass.bypass(url, strategy=strategy)
