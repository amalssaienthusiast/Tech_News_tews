import asyncio
import logging
import re
import time
from typing import Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass

import aiohttp
from bs4 import BeautifulSoup

# Local imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.exceptions import RateLimitedError
from src.bypass.browser_engine import StealthBrowser

logger = logging.getLogger(__name__)

class ProtectionType(Enum):
    """Types of anti-bot protection."""
    UNKNOWN = "unknown"
    NONE = "none"
    CLOUDFLARE = "cloudflare"
    CLOUDFLARE_CHALLENGE = "cloudflare_challenge"  # For JS challenge pages
    IMPERVA = "imperva"
    DATADOME = "datadome"
    AKAMAI = "akamai"
    PERIMETERX = "perimeterx"
    PAYWALL = "paywall"

@dataclass
class BypassResult:
    """Result of a bypass attempt."""
    success: bool
    content: Optional[str] = None
    protection_type: ProtectionType = ProtectionType.UNKNOWN
    error: Optional[str] = None
    metadata: Optional[dict] = None

class AntiBotBypass:
    """
    Handles anti-bot detection and bypass strategies.
    """

    # Patterns that indicate a DEFINITE blocking page (challenge/error pages)
    # These patterns should be specific enough to not match legitimate content
    BLOCK_PATTERNS = [
        r"access denied",
        r"you have been blocked",
        r"checking your browser before",  # More specific
        r"enable javascript and cookies to continue",  # More specific
        r"please complete the security check",
        r"ray id:",  # Cloudflare Ray ID - specific to challenge pages
        r"please wait while we verify",
        r"403 forbidden",
        r"service unavailable",
        r"attention required",  # Cloudflare attention page
    ]
    
    # Google Cache / error page patterns
    GOOGLE_ERROR_PATTERNS = [
        r"<title>google search",  # Google Cache error page
        r"if you're having trouble accessing google",
        r"the requested url was not found",
        r"error 404",
        r"page not found",
        r"this page isn't available",
    ]

    # Soft Paywall / Teaser Detection
    # These phrases indicate we successfully loaded a page, but it's not the full article
    PAYWALL_PATTERNS = [
        "subscribe to read",
        "subscribe to continue",
        "log in to continue",
        "sign up to read",
        "subscribe now to continue reading",
        "article is for subscribers only",
        "read the full story",
        "create an account",
        "start your free trial",
        "already a subscriber",
        "this article is exclusive",
        "join now to read",
        "unlock this article",
        "upgrade to premium",
    ]

    def __init__(self, max_retries: int = 3):
        self._browser: Optional[StealthBrowser] = None
        self.max_retries = max_retries
        
        # Rate limiting and delays (increased for anti-bot evasion)
        self._request_delay = 5  # Increased from 2 to 5 seconds
        self._min_delay = 2
        self._max_delay = 30
        
        # Blocked domains (known to aggressively block scrapers)
        self._blocked_domains = {
            'analyticsindiamag.com',  # Aggressive anti-bot
            # Add more as discovered
        }
        
        # Failure tracking for exponential backoff
        self._failure_counts: dict = {}  # domain -> failure count
        self._domain_last_request: dict = {}  # domain -> timestamp
        self._backoff_multiplier = 2  # Exponential backoff multiplier
    
    def is_domain_blocked(self, url: str) -> bool:
        """Check if domain is in blocked list."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower()
            # Check exact match and parent domain
            for blocked in self._blocked_domains:
                if blocked in domain:
                    logger.info(f"⛔ Domain blocked: {domain}")
                    return True
            return False
        except Exception as e:
            logger.warning(f"is_domain_blocked: suppressed {type(e).__name__}: {e}")
            return False
    
    def get_delay_for_domain(self, url: str) -> float:
        """Get delay with exponential backoff based on failure count."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            failures = self._failure_counts.get(domain, 0)
            
            # Exponential backoff: delay * (2 ^ failures)
            delay = self._request_delay * (self._backoff_multiplier ** failures)
            return min(delay, self._max_delay)
        except Exception as e:
            logger.debug(f"get_delay_for_domain: suppressed {type(e).__name__}: {e}")
            return self._request_delay
    
    def record_failure(self, url: str):
        """Record a failure for exponential backoff."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            self._failure_counts[domain] = self._failure_counts.get(domain, 0) + 1
            logger.debug(f"Recorded failure for {domain}, count: {self._failure_counts[domain]}")
        except Exception as e:
            logger.debug(f"record_failure: suppressed {type(e).__name__}: {e}")
            pass
    
    def record_success(self, url: str):
        """Reset failure count on success."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            if domain in self._failure_counts:
                del self._failure_counts[domain]
        except Exception as e:
            logger.debug(f"record_success: suppressed {type(e).__name__}: {e}")
            pass

    async def close(self) -> None:
        """Clean up resources."""
        if self._browser:
            await self._browser.close()
            self._browser = None

    def detect_protection(self, html: str, headers: dict = None) -> ProtectionType:
        """
        Detect the type of anti-bot protection on a page.
        
        Args:
            html: Page HTML content
            headers: Response headers (optional)
            
        Returns:
            ProtectionType enum indicating protection type
        """
        text = html.lower()
        headers = headers or {}
        
        # Cloudflare Challenge detection
        if "cf-browser-verification" in text or "checking your browser" in text:
            return ProtectionType.CLOUDFLARE_CHALLENGE
        if "cloudflare" in text and ("ray id" in text or "enable javascript" in text):
            return ProtectionType.CLOUDFLARE
        
        # Imperva/Incapsula
        if "imperva" in text or "incapsula" in text or "_incap_" in text:
            return ProtectionType.IMPERVA
        
        # DataDome
        if "datadome" in text or "dd.js" in text:
            return ProtectionType.DATADOME
        
        # Akamai
        if "akamai" in text or "ak_bmsc" in str(headers):
            return ProtectionType.AKAMAI
        
        # PerimeterX
        if "perimeterx" in text or "_px" in text:
            return ProtectionType.PERIMETERX
        
        # No protection detected
        return ProtectionType.NONE

    def is_blocked_sync(self, html: str, status_code: int = 200) -> bool:
        """
        Synchronous version of is_blocked for backward compatibility.
        
        Args:
            html: Page HTML content
            status_code: HTTP response status code
            
        Returns:
            True if content appears blocked/paywalled
        """
        # Empty or very short content
        if not html or len(html.strip()) < 100:
            return True
        
        # Error status codes
        if status_code in (403, 429, 503):
            return True
        
        text = html.lower()
        
        # Check for hard block patterns
        for pattern in self.BLOCK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        
        return False
    
    # Alias for backward compatibility with tests
    def is_blocked(self, html: str, status_code: int = 200) -> bool:
        """Backward-compatible sync is_blocked method."""
        return self.is_blocked_sync(html, status_code)

    async def is_blocked_async(self, html: str, url: str) -> bool:
        """
        Check if the fetched content indicates a block or soft paywall.
        
        Uses smart content-length validation to prevent false positives:
        - Check Google/error patterns on ALL pages (they can be large)
        - Only check Cloudflare patterns on short pages (<10KB)
        - Paywall detection requires both indicators AND low word count
        """
        content_length = len(html)
        text = html.lower()
        
        # FIRST: Check for Google Cache error pages (can be large HTML)
        for pattern in self.GOOGLE_ERROR_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.info(f"🚫 Block detected (Error Page): '{pattern}' in {url}")
                return True
        
        # CRITICAL: For truly large content (>50KB), only block if word count is very low
        if content_length > 50000:  # >50KB
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            word_count = len(soup.get_text(separator=' ', strip=True).split())
            
            # Large HTML but very few words = error page or broken content
            if word_count < 100:
                logger.warning(f"🚫 Large HTML ({content_length} chars) but only {word_count} words: {url}")
                return True
            
            logger.debug(f"✅ Large valid content ({content_length} chars, {word_count} words): {url}")
            return False
        
        # Only check hard block patterns on SHORT pages (<10KB)
        if content_length < 10000:
            for pattern in self.BLOCK_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    logger.info(f"🚫 Block detected (Challenge Page): '{pattern}' in {url}")
                    return True

        # Soft Paywall / Teaser Detection
        has_paywall_indicator = any(
            phrase in text 
            for phrase in self.PAYWALL_PATTERNS
        )

        # Parse and clean content to get accurate word count
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove noise elements
        for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'iframe', 'aside', 'form', 'button', 'noscript']):
            element.decompose()
        
        clean_text = soup.get_text(separator=' ', strip=True)
        word_count = len(clean_text.split())
        
        # Log analysis results
        if has_paywall_indicator:
            logger.info(f"⚠️ Paywall indicator in {url}. Words: {word_count}")
        
        # Paywall detection: indicator + low word count
        if has_paywall_indicator and word_count < 400:
            logger.warning(f"🚫 Soft paywall detected ({word_count} words) for {url}")
            return True
        
        # Extremely short content (even without indicators) is likely failed
        if word_count < 100:  # Reduced from 150 to be less aggressive
            logger.warning(f"🚫 Content too short ({word_count} words) for {url}")
            return True

        return False

    async def smart_fetch_with_fallback(self, url: str) -> Tuple[str, str]:
        """
        Try multiple strategies to fetch the URL.
        
        Returns:
            Tuple of (content, strategy_name)
        """
        # Check if domain is blocked
        if self.is_domain_blocked(url):
            raise Exception(f"Domain is in blocked list")
        
        # Apply delay with exponential backoff
        delay = self.get_delay_for_domain(url)
        if delay > 0:
            logger.debug(f"Applying {delay:.1f}s delay before request")
            await asyncio.sleep(delay)
        
        strategies = [
            ("google_cache", self._fetch_google_cache),
            ("referer_spoof", self._fetch_with_referer),
            ("archive_today", self._fetch_archive_today),
            ("wayback_machine", self._fetch_wayback_machine),
            ("dom_manipulation", self._fetch_with_dom_manipulation),
        ]

        for strategy_name, strategy_func in strategies:
            try:
                logger.info(f"Attempting {strategy_name} bypass for {url}")
                content = await strategy_func(url)
                
                if content:
                    # Validate that we didn't just get a teaser
                    if await self.is_blocked_async(content, url):
                        logger.warning(f"Strategy {strategy_name} returned blocked/teaser content. Retrying...")
                        continue
                    
                    logger.info(f"Smart fetch success with strategy: {strategy_name}")
                    self.record_success(url)  # Reset backoff on success
                    return content, strategy_name
                else:
                    logger.warning(f"Strategy {strategy_name} returned no content.")
            except Exception as e:
                logger.error(f"Strategy {strategy_name} failed: {e}")
                continue

        # All strategies failed - record for backoff
        self.record_failure(url)
        raise Exception("All bypass strategies failed or returned paywalls.")

    # --- Strategy Implementations ---

    async def _fetch_google_cache(self, url: str) -> Optional[str]:
        """Fetch via Google Webcache."""
        cache_url = f"http://webcache.googleusercontent.com/search?q=cache:{url}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cache_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        # Google cache wraps content; specific extraction might be needed
                        return html
        except Exception as e:
            logger.debug(f"Google cache failed: {e}")
        return None

    async def _fetch_with_referer(self, url: str) -> Optional[str]:
        """Fetch with a fake Google Referer."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.google.com/"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.text()
        except Exception as e:
            logger.debug(f"Referer spoof failed: {e}")
        return None

    async def _fetch_archive_today(self, url: str) -> Optional[str]:
        """Fetch via archive.today (archive.is)."""
        # This usually requires a POST and then a poll, or a direct link if known.
        # Simplified implementation:
        try:
            async with aiohttp.ClientSession() as session:
                # Try direct link first (rarely works without ID)
                async with session.get(f"https://archive.today/{url}", timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.text()
                
                # If needed, implement POST submission logic here
        except Exception as e:
            logger.debug(f"Archive.today failed: {e}")
        return None

    async def _fetch_wayback_machine(self, url: str) -> Optional[str]:
        """Fetch via Wayback Machine."""
        api_url = f"http://archive.org/wayback/available?url={url}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("archived_snapshots", {}).get("closest"):
                            archive_url = data["archived_snapshots"]["closest"]["url"]
                            # Fetch the archived content
                            async with session.get(archive_url, timeout=aiohttp.ClientTimeout(total=15)) as arch_resp:
                                if arch_resp.status == 200:
                                    return await arch_resp.text()
        except Exception as e:
            logger.debug(f"Wayback machine failed: {e}")
        return None

    async def _fetch_with_dom_manipulation(self, url: str) -> Optional[str]:
        """
        Use Playwright StealthBrowser for JavaScript-rendered pages.
        
        This is the real DOM manipulation bypass that:
        1. Launches a headless browser with stealth settings
        2. Waits for JavaScript to render content
        3. Applies Neural DOM Eraser to remove overlays/paywalls
        4. Returns the fully rendered HTML
        """
        logger.info(f"🌐 Attempting Playwright DOM manipulation for: {url}")
        
        try:
            # Initialize browser if not already done
            if self._browser is None:
                self._browser = StealthBrowser()
            
            # Use full_bypass_suite for comprehensive JavaScript rendering 
            # with paywall removal, CSS scrubbing, and stealth
            content = await self._browser.full_bypass_suite(url)
            
            if content and len(content) > 500:
                logger.info(f"✅ DOM manipulation successful: {len(content)} chars")
                return content
            else:
                logger.warning(f"⚠️ DOM manipulation returned insufficient content")
                return None
                
        except Exception as e:
            logger.warning(f"DOM manipulation error: {e}")
            
            # Only tear down the browser if it's a fatal process error
            error_str = str(e).lower()
            fatal_errors = ["target closed", "targetclosed", "browser has been closed", "disconnected", "connection closed"]
            is_fatal = any(err in error_str for err in fatal_errors)
            
            if is_fatal and self._browser:
                logger.warning("Fatal browser error detected, resetting warm browser instance.")
                try:
                    await self._browser.close()
                except Exception as cleanup_e:
                    logger.debug(f"_fetch_with_dom_manipulation: suppressed {type(cleanup_e).__name__}: {cleanup_e}")
                self._browser = None
            else:
                logger.debug("Non-fatal page error, keeping browser warm.")
                
            return None

    async def fetch_with_bypass(self, url: str) -> BypassResult:
        """Alias for smart_fetch_with_fallback to maintain compatibility."""
        try:
            content, strategy = await self.smart_fetch_with_fallback(url)
            return BypassResult(
                success=True,
                content=content,
                protection_type=ProtectionType.NONE, # Mapping generic
                metadata={'strategy': strategy}
            )
        except Exception as e:
            logger.error(f"Bypass error: {e}")
            return BypassResult(success=False, error=str(e))
