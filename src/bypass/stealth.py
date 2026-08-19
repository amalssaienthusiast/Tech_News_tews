"""
Advanced stealth configuration for browser fingerprint evasion.

This module provides comprehensive utilities for evading bot detection through:
- Realistic browser fingerprints with randomization
- Googlebot/Bingbot User-Agent emulation for crawler access
- Random User-Agent rotation for regular browsers
- WebGL fingerprint randomization
- Viewport/screen randomization
- Header spoofing with modern Sec-CH-UA client hints
- Navigator property overrides
- Archive/cache URL generation for fallback access

The goal is to make automated requests appear as legitimate human traffic
or trusted search engine crawlers.

Inspired by puppeteer-extra-stealth plugin techniques.
"""

import random
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# BROWSER USER-AGENTS (Regular browsers)
# =============================================================================

USER_AGENTS: List[str] = [
    # Chrome on Windows (latest versions)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


# =============================================================================
# SEARCH ENGINE CRAWLER USER-AGENTS (for Googlebot emulation)
# =============================================================================

GOOGLEBOT_USER_AGENTS: List[str] = [
    # Googlebot Desktop
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; +http://www.google.com/bot.html) Chrome/W.X.Y.Z Safari/537.36",
    # Googlebot Smartphone
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    # Googlebot-News
    "Googlebot-News",
    # Google-Extended (for AI/LLM training crawler)
    "Google-Extended",
    # Googlebot-Image
    "Googlebot-Image/1.0",
    # Googlebot-Video
    "Googlebot-Video/1.0",
]

BINGBOT_USER_AGENTS: List[str] = [
    # Bingbot Desktop
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    # Bingbot Mobile
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    # MSNBot
    "msnbot/2.0b (+http://search.msn.com/msnbot.htm)",
]

OTHER_CRAWLER_USER_AGENTS: List[str] = [
    # Yahoo Slurp
    "Mozilla/5.0 (compatible; Yahoo! Slurp; http://help.yahoo.com/help/us/ysearch/slurp)",
    # DuckDuckBot
    "DuckDuckBot/1.1; (+http://duckduckgo.com/duckduckbot.html)",
    # Facebot (Facebook)
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    # Twitterbot
    "Twitterbot/1.0",
    # LinkedInBot
    "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
]


# =============================================================================
# WEBGL FINGERPRINT RANDOMIZATION (puppeteer-extra-stealth feature)
# =============================================================================

WEBGL_FINGERPRINTS: List[Dict[str, str]] = [
    # NVIDIA cards
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    # AMD cards
    {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    # Intel integrated
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    # macOS
    {"vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)"},
    {"vendor": "Google Inc. (Apple)", "renderer": "ANGLE (Apple, Apple M2, OpenGL 4.1)"},
]


# =============================================================================
# MEDIA CODECS (puppeteer-extra-stealth feature - chrome.getMediaConfig)
# =============================================================================

MEDIA_CODECS: List[Dict[str, Any]] = [
    {
        "video": {
            "contentType": "video/webm; codecs=\"vp8\"",
            "supported": True,
            "smooth": True,
            "powerEfficient": True,
        },
        "audio": {
            "contentType": "audio/webm; codecs=\"opus\"",
            "supported": True,
            "smooth": True,
            "powerEfficient": True,
        }
    },
    {
        "video": {
            "contentType": "video/mp4; codecs=\"avc1.42E01E\"",
            "supported": True,
            "smooth": True,
            "powerEfficient": True,
        },
        "audio": {
            "contentType": "audio/mp4; codecs=\"mp4a.40.2\"",
            "supported": True,
            "smooth": True,
            "powerEfficient": True,
        }
    }
]


# Common screen resolutions
VIEWPORT_SIZES: List[Tuple[int, int]] = [
    (1920, 1080),  # Full HD
    (1366, 768),   # HD
    (1536, 864),   # HD+
    (1440, 900),   # WXGA+
    (1280, 720),   # HD
    (2560, 1440),  # QHD
    (1680, 1050),  # WSXGA+
    (1280, 800),   # WXGA
    (3840, 2160),  # 4K
]

# Common timezones
TIMEZONES: List[str] = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Australia/Sydney",
    "Asia/Kolkata",
]

# Common languages
LANGUAGES: List[str] = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.9,fr;q=0.8",
    "en-US,en;q=0.9,de;q=0.8",
]

# Accept headers
ACCEPT_HEADERS: List[str] = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_random_user_agent() -> str:
    """
    Get a random realistic User-Agent string.
    
    Returns:
        Random User-Agent string from the pool.
    """
    return random.choice(USER_AGENTS)


def get_random_googlebot_ua() -> str:
    """
    Get a random Googlebot User-Agent string.
    
    Returns:
        Random Googlebot User-Agent for crawler emulation.
    """
    return random.choice(GOOGLEBOT_USER_AGENTS)


def get_random_bingbot_ua() -> str:
    """
    Get a random Bingbot User-Agent string.
    
    Returns:
        Random Bingbot User-Agent for crawler emulation.
    """
    return random.choice(BINGBOT_USER_AGENTS)


def get_random_viewport() -> Dict[str, int]:
    """
    Get a random viewport size.
    
    Returns:
        Dictionary with 'width' and 'height' keys.
    """
    width, height = random.choice(VIEWPORT_SIZES)
    return {"width": width, "height": height}


def get_random_timezone() -> str:
    """
    Get a random timezone.
    
    Returns:
        Timezone string (e.g., 'America/New_York').
    """
    return random.choice(TIMEZONES)


def get_random_webgl_fingerprint() -> Dict[str, str]:
    """
    Get a random WebGL fingerprint (vendor/renderer).
    
    Returns:
        Dictionary with 'vendor' and 'renderer' keys.
    """
    return random.choice(WEBGL_FINGERPRINTS)


def get_archive_urls(url: str) -> List[str]:
    """
    Generate fallback archive/cache URLs for content access.
    
    This is how LLMs often access paywalled content - by checking
    cached or archived versions of pages.
    
    Args:
        url: Original URL to get archive versions for.
    
    Returns:
        List of archive/cache URLs to try.
    """
    encoded_url = urllib.parse.quote(url, safe='')
    
    return [
        # Google Cache (most recent version)
        f"https://webcache.googleusercontent.com/search?q=cache:{encoded_url}",
        # Internet Archive Wayback Machine (latest available)
        f"https://web.archive.org/web/2/{url}",
        # Archive.today / Archive.is (most recent snapshot)
        f"https://archive.is/newest/{url}",
        # Archive.today search (find any snapshot)
        f"https://archive.is/{url}",
        # Google text-only cache
        f"https://webcache.googleusercontent.com/search?q=cache:{encoded_url}&strip=1",
    ]


def get_stealth_headers(
    referer: Optional[str] = None,
    custom_headers: Optional[Dict[str, str]] = None,
    include_client_hints: bool = True
) -> Dict[str, str]:
    """
    Generate stealth HTTP headers that mimic a real browser.
    
    Args:
        referer: Optional referer URL to include.
        custom_headers: Optional additional headers to merge.
        include_client_hints: Include modern Sec-CH-UA-* headers.
    
    Returns:
        Dictionary of HTTP headers.
    """
    ua = get_random_user_agent()
    
    headers = {
        "User-Agent": ua,
        "Accept": random.choice(ACCEPT_HEADERS),
        "Accept-Language": random.choice(LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    
    # Add modern Client Hints (Sec-CH-UA-*) for Chrome-based browsers
    if include_client_hints and "Chrome" in ua:
        # Extract Chrome version from UA
        try:
            chrome_version = ua.split("Chrome/")[1].split(".")[0]
        except (IndexError, AttributeError):
            chrome_version = "120"
        
        headers.update({
            "Sec-CH-UA": f'"Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}", "Not=A?Brand";v="99"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"' if "Windows" in ua else '"macOS"' if "Mac" in ua else '"Linux"',
        })
    
    if referer:
        headers["Referer"] = referer
    
    if custom_headers:
        headers.update(custom_headers)
    
    return headers


def get_googlebot_headers() -> Dict[str, str]:
    """
    Get headers for Googlebot crawler emulation.
    
    Note: Googlebot doesn't send Sec-Fetch-* headers or Client Hints.
    
    Returns:
        Headers mimicking Googlebot.
    """
    return {
        "User-Agent": get_random_googlebot_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        # Note: No DNT, no Sec-* headers for crawlers
    }


# =============================================================================
# STEALTH CONFIGURATION CLASS
# =============================================================================

@dataclass
class StealthConfig:
    """
    Complete stealth configuration for browser automation.
    
    Provides all necessary configuration to make browser automation
    appear as legitimate human traffic or trusted crawlers.
    
    Attributes:
        user_agent: Browser User-Agent string.
        viewport: Screen viewport dimensions.
        timezone: Browser timezone.
        locale: Browser locale/language.
        headers: HTTP headers for requests.
        webgl_vendor: WebGL vendor string for fingerprint.
        webgl_renderer: WebGL renderer string for fingerprint.
        hardware_concurrency: Simulated CPU cores.
        device_memory: Simulated device memory in GB.
        plugins: List of simulated browser plugins.
    """
    
    user_agent: str = field(default_factory=get_random_user_agent)
    viewport: Dict[str, int] = field(default_factory=get_random_viewport)
    timezone: str = field(default_factory=get_random_timezone)
    locale: str = field(default_factory=lambda: random.choice(LANGUAGES).split(",")[0])
    headers: Dict[str, str] = field(default_factory=dict)
    
    # Browser fingerprint properties (randomized for evasion)
    webgl_vendor: str = field(default_factory=lambda: get_random_webgl_fingerprint()["vendor"])
    webgl_renderer: str = field(default_factory=lambda: get_random_webgl_fingerprint()["renderer"])
    hardware_concurrency: int = field(default_factory=lambda: random.choice([4, 6, 8, 12, 16]))
    device_memory: int = field(default_factory=lambda: random.choice([4, 8, 16, 32]))
    plugins: List[str] = field(default_factory=lambda: [
        "Chrome PDF Plugin",
        "Chrome PDF Viewer",
        "Native Client",
    ])
    
    # Media codec info (for puppeteer-extra-stealth compatibility)
    media_codecs: Dict[str, Any] = field(default_factory=lambda: random.choice(MEDIA_CODECS))
    
    def __post_init__(self):
        """Initialize headers with stealth configuration."""
        if not self.headers:
            self.headers = get_stealth_headers()
        self.headers["User-Agent"] = self.user_agent
    
    def get_playwright_context_args(self) -> Dict[str, Any]:
        """
        Get arguments for Playwright browser context.
        
        Returns:
            Dictionary of Playwright context arguments.
        """
        return {
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "locale": self.locale,
            "timezone_id": self.timezone,
            "extra_http_headers": self.headers,
            "java_script_enabled": True,
            "ignore_https_errors": False,
        }
    
    def get_navigator_overrides(self) -> Dict[str, Any]:
        """
        Get navigator property overrides for stealth.
        
        Returns:
            Dictionary of navigator properties to override.
        """
        return {
            "hardwareConcurrency": self.hardware_concurrency,
            "deviceMemory": self.device_memory,
            "webdriver": False,
            "languages": [self.locale, "en"],
            "plugins": self.plugins,
            "webgl": {
                "vendor": self.webgl_vendor,
                "renderer": self.webgl_renderer,
            },
            "mediaCodecs": self.media_codecs,
        }
    
    def get_aiohttp_headers(self) -> Dict[str, str]:
        """
        Get headers optimized for aiohttp requests.
        
        Returns:
            Dictionary of HTTP headers.
        """
        return self.headers.copy()
    
    @classmethod
    def for_google_referer(cls) -> "StealthConfig":
        """
        Create config that appears as traffic from Google search.
        
        Returns:
            StealthConfig with Google referer.
        """
        config = cls()
        config.headers = get_stealth_headers(
            referer="https://www.google.com/",
            custom_headers={"Sec-Fetch-Site": "cross-site"}
        )
        return config
    
    @classmethod
    def for_social_referer(cls, platform: str = "twitter") -> "StealthConfig":
        """
        Create config that appears as traffic from social media.
        
        Args:
            platform: Social media platform ('twitter', 'facebook', 'linkedin').
        
        Returns:
            StealthConfig with social media referer.
        """
        referers = {
            "twitter": "https://t.co/",
            "facebook": "https://l.facebook.com/",
            "linkedin": "https://www.linkedin.com/",
            "reddit": "https://www.reddit.com/",
        }
        config = cls()
        config.headers = get_stealth_headers(
            referer=referers.get(platform, referers["twitter"]),
            custom_headers={"Sec-Fetch-Site": "cross-site"}
        )
        return config
    
    @classmethod
    def for_googlebot(cls) -> "StealthConfig":
        """
        Create config mimicking Googlebot crawler.
        
        Publishers often whitelist Googlebot for SEO purposes,
        allowing full content access. This is how LLMs often
        access paywalled content.
        
        Returns:
            StealthConfig with Googlebot User-Agent.
        """
        config = cls()
        config.user_agent = get_random_googlebot_ua()
        config.headers = get_googlebot_headers()
        return config
    
    @classmethod
    def for_bingbot(cls) -> "StealthConfig":
        """
        Create config mimicking Bingbot crawler.
        
        Returns:
            StealthConfig with Bingbot User-Agent.
        """
        config = cls()
        config.user_agent = get_random_bingbot_ua()
        config.headers = {
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        return config
    
    @classmethod
    def for_facebook_crawler(cls) -> "StealthConfig":
        """
        Create config mimicking Facebook's link preview crawler.
        
        Returns:
            StealthConfig with Facebot User-Agent.
        """
        config = cls()
        config.user_agent = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
        config.headers = {
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        return config
