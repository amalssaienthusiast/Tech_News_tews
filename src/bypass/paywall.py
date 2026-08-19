"""
Paywall bypass module for accessing paywalled content.

This module provides multiple strategies for bypassing soft paywalls:
1. Incognito Mode - Clear cookies to reset metered access
2. Google Cache - Use Google's cached version
3. Archive Services - Use archive.today or web.archive.org
4. Referer Spoof - Appear as Google/social traffic
5. DOM Manipulation - Remove paywall overlay elements

Note: Hard paywalls (server-side verification) cannot be bypassed.
Only soft/metered paywalls that rely on client-side enforcement.
"""

import asyncio
import logging
import re
import ssl
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from src.bypass.stealth import StealthConfig, get_stealth_headers

logger = logging.getLogger(__name__)


class PaywallMethod(Enum):
    """Available paywall bypass methods."""
    AUTO = "auto"
    INCOGNITO = "incognito"
    GOOGLE_CACHE = "google_cache"
    ARCHIVE_TODAY = "archive_today"
    WAYBACK = "wayback"
    REFERER_SPOOF = "referer_spoof"
    DOM_MANIPULATION = "dom_manipulation"


@dataclass
class PaywallResult:
    """Result of a paywall bypass attempt."""
    success: bool
    content: str
    method_used: PaywallMethod
    original_url: str
    bypass_url: Optional[str] = None
    error: Optional[str] = None


# Common paywall selectors
PAYWALL_SELECTORS: List[str] = [
    # Generic paywall classes
    ".paywall",
    ".subscription-wall",
    ".subscribe-wall",
    ".premium-wall",
    ".metered-content",
    ".meter-paywall",
    ".gate",
    ".article-gate",
    
    # Modal/overlay selectors
    ".modal",
    ".modal-backdrop",
    ".overlay",
    ".paywall-overlay",
    ".subscribe-overlay",
    
    # Specific site patterns
    "[data-paywall]",
    "[data-subscription-wall]",
    "[class*='paywall']",
    "[class*='subscription']",
    "[id*='paywall']",
    "[id*='subscribe-wall']",
    
    # Blur/fade effects
    ".blur-content",
    ".fade-content",
    ".truncated-content",
    
    # Login/signup walls
    ".login-wall",
    ".signup-wall",
    ".registration-wall",
    
    # ===== CONTENT PLATFORMS =====
    # Medium-specific
    'div[data-testid="paywall-overlay"]',
    'div[aria-label="Paywall"]',
    ".meteredContent",
    ".meteredFooter",
    ".metVis",
    'div[class*="meteredContent"]',
    ".overlay--gradient",
    
    # Substack-specific
    ".paywall-modal",
    ".paywall-cta",
    ".locked-content",
    ".PaidOnlyContent",
    ".paywall-bar",
    
    # Ghost CMS
    ".gh-paywall",
    ".subscribe-overlay",
    ".members-only-cta",
    ".kg-signup-card",
    ".members-only-blur",
]

# Patterns indicating paywall in HTML
PAYWALL_PATTERNS: List[str] = [
    r"subscribe to (continue|read|access)",
    r"subscription required",
    r"premium (article|content)",
    r"members only",
    r"exclusive (content|article)",
    r"log ?in to (continue|read)",
    r"create an? (account|free account)",
    r"you('ve| have) reached your (free )?article limit",
    r"free articles? remaining",
    r"unlock this (article|story)",
]

# Sites known to use specific paywall types
KNOWN_PAYWALL_SITES: Dict[str, PaywallMethod] = {
    # News sites
    "nytimes.com": PaywallMethod.GOOGLE_CACHE,
    "wsj.com": PaywallMethod.GOOGLE_CACHE,
    "washingtonpost.com": PaywallMethod.REFERER_SPOOF,
    "bloomberg.com": PaywallMethod.REFERER_SPOOF,
    "ft.com": PaywallMethod.GOOGLE_CACHE,
    "economist.com": PaywallMethod.ARCHIVE_TODAY,
    "theatlantic.com": PaywallMethod.INCOGNITO,
    "wired.com": PaywallMethod.INCOGNITO,
    
    # Content platforms - use DOM manipulation (Neural Eraser)
    "medium.com": PaywallMethod.DOM_MANIPULATION,
    "towardsdatascience.com": PaywallMethod.DOM_MANIPULATION,
    "betterprogramming.pub": PaywallMethod.DOM_MANIPULATION,
    "gitconnected.com": PaywallMethod.DOM_MANIPULATION,
    "levelup.gitconnected.com": PaywallMethod.DOM_MANIPULATION,
    "substack.com": PaywallMethod.REFERER_SPOOF,
    "ghost.io": PaywallMethod.DOM_MANIPULATION,
    "hashnode.dev": PaywallMethod.REFERER_SPOOF,
}


class PaywallBypass:
    """
    Paywall detection and bypass handler.
    
    Provides multiple strategies for accessing paywalled content.
    Automatically selects the best method based on the site.
    
    Attributes:
        stealth_config: Stealth configuration for requests.
        timeout: Request timeout in seconds.
        custom_selectors: Additional CSS selectors for paywall detection.
    
    Example:
        bypass = PaywallBypass()
        result = await bypass.bypass_paywall("https://news-site.com/article")
        if result.success:
            print(result.content)
    """
    
    def __init__(
        self,
        stealth_config: Optional[StealthConfig] = None,
        timeout: int = 30,
        custom_selectors: Optional[List[str]] = None
    ):
        """
        Initialize paywall bypass handler.
        
        Args:
            stealth_config: Optional stealth configuration.
            timeout: Request timeout in seconds.
            custom_selectors: Additional paywall CSS selectors.
        """
        self.stealth_config = stealth_config or StealthConfig()
        self.timeout = timeout
        self.selectors = PAYWALL_SELECTORS.copy()
        if custom_selectors:
            self.selectors.extend(custom_selectors)
        self._session: Optional[aiohttp.ClientSession] = None
        self._browser = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            # Create session without cookies (incognito-like)
            self._session = aiohttp.ClientSession(
                headers=self.stealth_config.get_aiohttp_headers(),
                cookie_jar=aiohttp.CookieJar(),
            )
        return self._session
    
    async def close(self) -> None:
        """Close the aiohttp session and stealth browser."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
        if getattr(self, '_browser', None) is not None:
            try:
                await self._browser.close()
            except Exception as e:
                logger.debug(f"Error closing browser in PaywallBypass: {e}")
            self._browser = None
    
    def detect_paywall(self, html: str) -> bool:
        """
        Detect if content is behind a paywall.
        
        Args:
            html: Page HTML content.
        
        Returns:
            True if paywall detected, False otherwise.
        """
        html_lower = html.lower()
        
        # Check for paywall patterns in text
        for pattern in PAYWALL_PATTERNS:
            if re.search(pattern, html_lower, re.IGNORECASE):
                return True
        
        # Parse HTML and check for paywall elements
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            for selector in self.selectors:
                if soup.select(selector):
                    return True
            
            # Check for truncated content indicators
            article = soup.find("article") or soup.find(class_=re.compile(r"article|content|story"))
            if article:
                # Very short article text might indicate paywall
                text = article.get_text(strip=True)
                if len(text) < 500 and "subscribe" in html_lower:
                    return True
                    
        except Exception as e:
            logger.warning(f"Error parsing HTML for paywall detection: {e}")
        
        return False
    
    def auto_select_method(self, url: str) -> PaywallMethod:
        """
        Automatically select the best bypass method for a URL.
        
        Args:
            url: URL to bypass.
        
        Returns:
            Recommended PaywallMethod.
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        
        # Check known sites
        for site, method in KNOWN_PAYWALL_SITES.items():
            if site in domain:
                return method
        
        # Default to referer spoof (works for many sites)
        return PaywallMethod.REFERER_SPOOF
    
    async def bypass_paywall(
        self,
        url: str,
        method: PaywallMethod = PaywallMethod.AUTO,
        fallback: bool = True
    ) -> PaywallResult:
        """
        Bypass paywall using the specified method.
        
        Args:
            url: URL to access.
            method: Bypass method to use.
            fallback: Try other methods if first fails.
        
        Returns:
            PaywallResult with content.
        """
        if method == PaywallMethod.AUTO:
            method = self.auto_select_method(url)
        
        # Define method priority for fallback
        methods = [method]
        if fallback:
            all_methods = [
                PaywallMethod.REFERER_SPOOF,
                PaywallMethod.GOOGLE_CACHE,
                PaywallMethod.INCOGNITO,
                PaywallMethod.ARCHIVE_TODAY,
                PaywallMethod.WAYBACK,
                PaywallMethod.DOM_MANIPULATION,
            ]
            for m in all_methods:
                if m not in methods:
                    methods.append(m)
        
        last_error = None
        for m in methods:
            try:
                result = await self._try_method(url, m)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Bypass method {m.value} failed: {e}")
        
        return PaywallResult(
            success=False,
            content="",
            method_used=method,
            original_url=url,
            error=last_error or "All bypass methods failed",
        )
    
    async def _try_method(self, url: str, method: PaywallMethod) -> PaywallResult:
        """Try a specific bypass method."""
        if method == PaywallMethod.INCOGNITO:
            return await self.incognito_bypass(url)
        elif method == PaywallMethod.GOOGLE_CACHE:
            return await self.google_cache_bypass(url)
        elif method == PaywallMethod.ARCHIVE_TODAY:
            return await self.archive_today_bypass(url)
        elif method == PaywallMethod.WAYBACK:
            return await self.wayback_bypass(url)
        elif method == PaywallMethod.REFERER_SPOOF:
            return await self.referer_spoof_bypass(url)
        elif method == PaywallMethod.DOM_MANIPULATION:
            return await self.dom_manipulation_bypass(url)
        else:
            return PaywallResult(
                success=False,
                content="",
                method_used=method,
                original_url=url,
                error=f"Unknown method: {method}",
            )
    
    async def incognito_bypass(self, url: str) -> PaywallResult:
        """
        Bypass using fresh session (no cookies).
        
        Works for metered paywalls that track article count via cookies.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with content.
        """
        logger.info(f"Attempting incognito bypass for {url}")
        
        try:
            # Create fresh session with no cookies
            async with aiohttp.ClientSession(
                headers=get_stealth_headers(),
                cookie_jar=aiohttp.DummyCookieJar(),  # Ignores cookies
            ) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    html = await response.text()
                    
                    if not self.detect_paywall(html):
                        return PaywallResult(
                            success=True,
                            content=html,
                            method_used=PaywallMethod.INCOGNITO,
                            original_url=url,
                        )
                    
                    return PaywallResult(
                        success=False,
                        content=html,
                        method_used=PaywallMethod.INCOGNITO,
                        original_url=url,
                        error="Paywall still present after incognito",
                    )
                    
        except Exception as e:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.INCOGNITO,
                original_url=url,
                error=str(e),
            )
    
    async def google_cache_bypass(self, url: str) -> PaywallResult:
        """
        Bypass using Google's cached version of the page.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with cached content.
        """
        logger.info(f"Attempting Google cache bypass for {url}")
        
        cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{quote_plus(url)}"
        
        try:
            session = await self._get_session()
            
            async with session.get(
                cache_url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status == 200:
                    html = await response.text()
                    return PaywallResult(
                        success=True,
                        content=html,
                        method_used=PaywallMethod.GOOGLE_CACHE,
                        original_url=url,
                        bypass_url=cache_url,
                    )
                else:
                    return PaywallResult(
                        success=False,
                        content="",
                        method_used=PaywallMethod.GOOGLE_CACHE,
                        original_url=url,
                        error=f"Cache returned status {response.status}",
                    )
                    
        except Exception as e:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.GOOGLE_CACHE,
                original_url=url,
                error=str(e),
            )
    
    async def archive_today_bypass(self, url: str) -> PaywallResult:
        """
        Bypass using archive.today.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with archived content.
        """
        logger.info(f"Attempting archive.today bypass for {url}")
        
        # Check existing archives first
        archive_url = f"https://archive.today/{url}"
        
        try:
            session = await self._get_session()
            
            async with session.get(
                archive_url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                allow_redirects=True,
            ) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    # Check if we got the actual archived page
                    if len(html) > 1000 and "archive" in str(response.url):
                        return PaywallResult(
                            success=True,
                            content=html,
                            method_used=PaywallMethod.ARCHIVE_TODAY,
                            original_url=url,
                            bypass_url=str(response.url),
                        )
                
                return PaywallResult(
                    success=False,
                    content="",
                    method_used=PaywallMethod.ARCHIVE_TODAY,
                    original_url=url,
                    error="No archive found",
                )
                
        except Exception as e:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.ARCHIVE_TODAY,
                original_url=url,
                error=str(e),
            )
    
    async def wayback_bypass(self, url: str) -> PaywallResult:
        """
        Bypass using Internet Archive's Wayback Machine.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with archived content.
        """
        logger.info(f"Attempting Wayback Machine bypass for {url}")
        
        # Check for existing snapshot
        check_url = f"https://archive.org/wayback/available?url={quote_plus(url)}"
        
        try:
            session = await self._get_session()
            
            async with session.get(
                check_url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                data = await response.json()
                
                if data.get("archived_snapshots", {}).get("closest", {}).get("available"):
                    snapshot_url = data["archived_snapshots"]["closest"]["url"]
                    
                    # Fetch the snapshot
                    async with session.get(
                        snapshot_url,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as snap_response:
                        if snap_response.status == 200:
                            html = await snap_response.text()
                            return PaywallResult(
                                success=True,
                                content=html,
                                method_used=PaywallMethod.WAYBACK,
                                original_url=url,
                                bypass_url=snapshot_url,
                            )
                
                return PaywallResult(
                    success=False,
                    content="",
                    method_used=PaywallMethod.WAYBACK,
                    original_url=url,
                    error="No Wayback snapshot available",
                )
                
        except Exception as e:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.WAYBACK,
                original_url=url,
                error=str(e),
            )
    
    async def referer_spoof_bypass(self, url: str) -> PaywallResult:
        """
        Bypass by appearing as traffic from Google/social media.
        
        Many sites allow free access to users coming from search engines.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with content.
        """
        logger.info(f"Attempting referer spoof bypass for {url}")
        
        # Try different referers
        referers = [
            ("Google", "https://www.google.com/"),
            ("Google News", "https://news.google.com/"),
            ("Twitter", "https://t.co/"),
            ("Facebook", "https://l.facebook.com/"),
            ("LinkedIn", "https://www.linkedin.com/"),
        ]
        
        for name, referer in referers:
            try:
                headers = get_stealth_headers(
                    referer=referer,
                    custom_headers={"Sec-Fetch-Site": "cross-site"}
                )
                
                async with aiohttp.ClientSession(
                    headers=headers,
                    cookie_jar=aiohttp.DummyCookieJar(),
                ) as session:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        html = await response.text()
                        
                        if not self.detect_paywall(html):
                            return PaywallResult(
                                success=True,
                                content=html,
                                method_used=PaywallMethod.REFERER_SPOOF,
                                original_url=url,
                            )
                            
            except Exception as e:
                logger.debug(f"Referer {name} failed: {e}")
        
        return PaywallResult(
            success=False,
            content="",
            method_used=PaywallMethod.REFERER_SPOOF,
            original_url=url,
            error="All referer spoofs failed",
        )
    
    async def dom_manipulation_bypass(self, url: str) -> PaywallResult:
        """
        Bypass by removing paywall overlay elements.
        
        This requires browser automation to execute JavaScript.
        Falls back to removing elements from static HTML.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with cleaned content.
        """
        logger.info(f"Attempting DOM manipulation bypass for {url}")
        
        try:
            session = await self._get_session()
            
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                html = await response.text()
                
                # Remove paywall elements from HTML
                soup = BeautifulSoup(html, "html.parser")
                
                # Remove paywall overlays
                for selector in self.selectors:
                    for element in soup.select(selector):
                        element.decompose()
                
                # Semantic Neural Eraser (Static Fallback)
                # Removes elements with blocking keywords that look like overlays
                keywords = ['subscribe', 'plan', 'member', 'unlock', 'register', 'limit', 'access', 'premium']
                for element in soup.find_all(['div', 'section', 'aside', 'footer']):
                    # Check text content
                    text = element.get_text(separator=" ", strip=True).lower()
                    if len(text) > 500 or len(text) < 5:
                        continue
                        
                    # Check for overlay-like keywords
                    if any(kw in text for kw in keywords):
                        # Heuristic: If it has inline style z-index or fixed position
                        style = element.get("style", "").lower()
                        if "z-index" in style or "fixed" in style or "absolute" in style:
                            element.decompose()
                            continue
                        
                        # Heuristic: If it's a short text block at the end of body
                        if len(text) < 200 and element.name == "div":
                            element.decompose()

                # Remove blur/fade styles
                for element in soup.find_all(style=True):
                    style = element.get("style", "")
                    if any(s in style for s in ["blur", "filter", "opacity"]):
                        del element["style"]
                
                # Remove elements hiding content
                for element in soup.find_all(style=re.compile(r"display\s*:\s*none")):
                    del element["style"]
                
                cleaned_html = str(soup)
                
                return PaywallResult(
                    success=True,
                    content=cleaned_html,
                    method_used=PaywallMethod.DOM_MANIPULATION,
                    original_url=url,
                )
                
        except Exception as e:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.DOM_MANIPULATION,
                original_url=url,
                error=str(e),
            )
    
    async def _get_browser(self):
        """Get or initialize the stealth browser."""
        if self._browser is None:
            from src.bypass.browser_engine import StealthBrowser
            self._browser = StealthBrowser(headless=True)
            await self._browser.initialize()
        return self._browser

    async def dom_manipulation_with_browser(self, url: str) -> PaywallResult:
        """
        Bypass using Playwright for JavaScript-based paywalls.
        
        Uses browser automation to remove paywall elements after page load.
        
        Args:
            url: URL to access.
        
        Returns:
            PaywallResult with cleaned content.
        """
        try:
            browser = await self._get_browser()
            
            content = await browser.fetch_with_bypass(url, "paywall")
            return PaywallResult(
                success=True,
                content=content,
                method_used=PaywallMethod.DOM_MANIPULATION,
                original_url=url,
            )
                
        except ImportError:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.DOM_MANIPULATION,
                original_url=url,
                error="Playwright not installed",
            )
        except Exception as e:
            return PaywallResult(
                success=False,
                content="",
                method_used=PaywallMethod.DOM_MANIPULATION,
                original_url=url,
                error=str(e),
            )
