"""
TLS Fingerprint Randomization - Evade JA3-based bot detection.

This module uses curl-cffi to impersonate real browser TLS fingerprints,
making requests indistinguishable from legitimate browsers.

Features:
- Chrome/Firefox/Safari TLS fingerprint impersonation
- Automatic rotation between browser signatures
- HTTP/2 support with proper fingerprinting
- Cookie and session management
- Async and sync request support

Usage:
    from src.bypass.tls_client import TLSClient
    
    async with TLSClient() as client:
        response = await client.get("https://example.com")
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import AsyncSession, Response
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    curl_requests = None
    AsyncSession = None
    Response = None

logger = logging.getLogger(__name__)


class BrowserProfile(Enum):
    """Browser TLS fingerprint profiles.

    Ordered newest-first within each browser family so that rotation
    picks the freshest profiles. Older profiles (chrome119, chrome116,
    etc.) are kept for backwards compatibility but should not be the
    default — sites that fingerprint TLS clients are more likely to
    have current Chrome in their allowlist than a 2-year-old version.
    """
    # Chrome profiles (newest first)
    CHROME_131 = "chrome131"
    CHROME_124 = "chrome124"
    CHROME_120 = "chrome120"
    CHROME_119 = "chrome119"
    CHROME_116 = "chrome116"
    CHROME_110 = "chrome110"
    CHROME_107 = "chrome107"
    CHROME_104 = "chrome104"

    # Firefox profiles (newest first)
    FIREFOX_133 = "firefox133"
    FIREFOX_120 = "firefox120"
    FIREFOX_117 = "firefox117"
    FIREFOX_110 = "firefox110"

    # Safari profiles (newest first)
    SAFARI_17_5 = "safari17_5"
    SAFARI_17_0 = "safari17_0"
    SAFARI_16_0 = "safari16_0"
    SAFARI_15_5 = "safari15_5"

    # Edge profiles
    EDGE_120 = "edge120"
    EDGE_101 = "edge101"


# Browser profiles by category for smart rotation (newest-first)
CHROME_PROFILES = [
    BrowserProfile.CHROME_131,
    BrowserProfile.CHROME_124,
    BrowserProfile.CHROME_120,
    BrowserProfile.CHROME_119,
    BrowserProfile.CHROME_116,
    BrowserProfile.CHROME_110,
]

FIREFOX_PROFILES = [
    BrowserProfile.FIREFOX_133,
    BrowserProfile.FIREFOX_120,
    BrowserProfile.FIREFOX_117,
    BrowserProfile.FIREFOX_110,
]

SAFARI_PROFILES = [
    BrowserProfile.SAFARI_17_5,
    BrowserProfile.SAFARI_17_0,
    BrowserProfile.SAFARI_16_0,
    BrowserProfile.SAFARI_15_5,
]

ALL_PROFILES = CHROME_PROFILES + FIREFOX_PROFILES + SAFARI_PROFILES


@dataclass
class TLSConfig:
    """TLS client configuration."""
    profile: BrowserProfile = BrowserProfile.CHROME_131
    timeout: int = 30
    follow_redirects: bool = True
    verify_ssl: bool = True
    proxy: Optional[str] = None
    
    # Headers matching browser profile
    headers: Optional[Dict[str, str]] = None


# Default headers matching Chrome 120
CHROME_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

FIREFOX_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
}

SAFARI_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
}


def get_headers_for_profile(profile: BrowserProfile) -> Dict[str, str]:
    """Get appropriate headers for browser profile."""
    if profile in CHROME_PROFILES:
        return CHROME_HEADERS.copy()
    elif profile in FIREFOX_PROFILES:
        return FIREFOX_HEADERS.copy()
    elif profile in SAFARI_PROFILES:
        return SAFARI_HEADERS.copy()
    else:
        return CHROME_HEADERS.copy()


class TLSClient:
    """
    HTTP client with TLS fingerprint impersonation.
    
    Uses curl_cffi to make requests with real browser TLS fingerprints,
    bypassing JA3-based bot detection.
    """
    
    def __init__(
        self,
        config: Optional[TLSConfig] = None,
        rotate_profile: bool = True,
        profile_categories: Optional[List[List[BrowserProfile]]] = None,
    ) -> None:
        """
        Initialize TLS client.
        
        Args:
            config: TLS configuration
            rotate_profile: If True, rotate profiles between requests
            profile_categories: List of profile groups to rotate through
        """
        if not HAS_CURL_CFFI:
            raise ImportError(
                "curl_cffi required for TLS fingerprinting. "
                "Install with: pip install curl-cffi"
            )
        
        self.config = config or TLSConfig()
        self.rotate_profile = rotate_profile
        self.profile_categories = profile_categories or [
            CHROME_PROFILES,
            FIREFOX_PROFILES,
        ]
        
        self._session: Optional[AsyncSession] = None
        self._current_profile = self.config.profile
        self._request_count = 0
        
        # Stats
        self._stats = {
            "requests": 0,
            "success": 0,
            "failed": 0,
            "profile_rotations": 0,
        }
    
    async def __aenter__(self) -> "TLSClient":
        """Async context manager entry."""
        await self._create_session()
        return self
    
    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()
    
    async def _create_session(self) -> None:
        """Create new session with current profile."""
        if self._session:
            await self._session.close()
        
        self._session = AsyncSession(
            impersonate=self._current_profile.value,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            proxies={"all": self.config.proxy} if self.config.proxy else None,
        )
    
    def _rotate_profile(self) -> None:
        """Rotate to a different browser profile."""
        if not self.rotate_profile:
            return
        
        # Pick random category
        category = random.choice(self.profile_categories)
        
        # Pick random profile from category (different from current)
        available = [p for p in category if p != self._current_profile]
        if available:
            self._current_profile = random.choice(available)
            self._stats["profile_rotations"] += 1
            logger.debug(f"Rotated to profile: {self._current_profile.value}")
    
    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> "Response":
        """
        Make GET request with TLS fingerprinting.
        
        Args:
            url: Target URL
            headers: Optional additional headers
            params: Query parameters
            **kwargs: Additional arguments passed to curl_cffi
        
        Returns:
            Response object
        """
        return await self._request("GET", url, headers=headers, params=params, **kwargs)
    
    async def post(
        self,
        url: str,
        data: Optional[Dict] = None,
        json: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> "Response":
        """Make POST request with TLS fingerprinting."""
        return await self._request(
            "POST", url, data=data, json=json, headers=headers, **kwargs
        )
    
    async def _request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> "Response":
        """Make HTTP request with TLS fingerprinting."""
        
        # Rotate profile periodically
        self._request_count += 1
        if self._request_count % 10 == 0:  # Rotate every 10 requests
            self._rotate_profile()
            await self._create_session()
        
        # Build headers
        request_headers = get_headers_for_profile(self._current_profile)
        if self.config.headers:
            request_headers.update(self.config.headers)
        if headers:
            request_headers.update(headers)
        
        # Ensure session exists
        if not self._session:
            await self._create_session()
        
        try:
            self._stats["requests"] += 1
            
            response = await self._session.request(
                method,
                url,
                headers=request_headers,
                allow_redirects=self.config.follow_redirects,
                **kwargs,
            )
            
            self._stats["success"] += 1
            return response
            
        except Exception as e:
            self._stats["failed"] += 1
            logger.error(f"TLS request failed: {e}")
            raise
    
    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.close()
            self._session = None
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            **self._stats,
            "current_profile": self._current_profile.value,
            "rotate_enabled": self.rotate_profile,
        }
    
    @property
    def current_profile(self) -> str:
        """Get current browser profile."""
        return self._current_profile.value


# Convenience function for quick requests
async def tls_get(
    url: str,
    profile: Optional[BrowserProfile] = None,
    **kwargs,
) -> "Response":
    """
    Quick GET request with TLS fingerprinting.
    
    Args:
        url: Target URL
        profile: Browser profile to impersonate
        **kwargs: Additional request arguments
    
    Returns:
        Response object
    """
    config = TLSConfig(profile=profile or BrowserProfile.CHROME_120)
    
    async with TLSClient(config=config, rotate_profile=False) as client:
        return await client.get(url, **kwargs)


async def tls_post(url: str, **kwargs) -> "Response":
    """Quick POST request with TLS fingerprinting."""
    async with TLSClient(rotate_profile=False) as client:
        return await client.post(url, **kwargs)
