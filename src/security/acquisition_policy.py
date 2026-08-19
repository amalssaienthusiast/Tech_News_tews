"""
Authoritative Outbound Acquisition Security Policy & Boundary Gateway.
Location: src/security/acquisition_policy.py

This module establishes the single authoritative security boundary for all outbound
network acquisitions across the Tech News Scrapper system.

Guarantees:
1. Every outbound target URL is pre-flight validated for syntax and scheme.
2. Every target hostname is DNS-resolved and validated against prohibited networks
   (Loopback, RFC 1918 Private, Link-Local, Cloud Metadata 169.254.169.254, CGNAT,
   IPv6 ULA, and IPv4-mapped IPv6).
3. Multi-hop HTTP redirects are validated on every single hop to prevent SSRF bypasses.
4. Streaming response size (raw and decompressed) is bounded to prevent decompression bombs.
5. Robots.txt politeness policies are evaluated asynchronously through SSRF-protected channels.
6. Strict TLS certificate validation is enforced default-on.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC, timedelta
import ipaddress
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.robotparser
from urllib.parse import urljoin, urlparse

from .ssrf_guard import (
    PayloadSizeLimitExceeded,
    SSRFConfig,
    SSRFGuard,
    SSRFSecurityError,
    SafeHttpClient,
)
from ..network.fetch_policy import FetchPolicy

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared Global Singletons
# ─────────────────────────────────────────────────────────────────────────────
_global_ssrf_guard: Optional[SSRFGuard] = None
_global_safe_http_client: Optional[SafeHttpClient] = None


def get_acquisition_ssrf_guard() -> SSRFGuard:
    """Return the global SSRFGuard singleton."""
    global _global_ssrf_guard
    if _global_ssrf_guard is None:
        _global_ssrf_guard = SSRFGuard()
    return _global_ssrf_guard


def set_acquisition_ssrf_guard(guard: Optional[SSRFGuard]) -> None:
    """Inject custom SSRFGuard for testing."""
    global _global_ssrf_guard
    _global_ssrf_guard = guard


def get_safe_http_client() -> SafeHttpClient:
    """Return the global SafeHttpClient singleton."""
    global _global_safe_http_client
    if _global_safe_http_client is None:
        _global_safe_http_client = SafeHttpClient(guard=get_acquisition_ssrf_guard())
    return _global_safe_http_client


def set_safe_http_client(client: Optional[SafeHttpClient]) -> None:
    """Inject custom SafeHttpClient for testing."""
    global _global_safe_http_client
    _global_safe_http_client = client


# ─────────────────────────────────────────────────────────────────────────────
# Authoritative URL Validation Contract
# ─────────────────────────────────────────────────────────────────────────────
def validate_acquisition_url(url: str) -> Tuple[str, List[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    """
    Validate target URL syntax, scheme, and DNS resolution against forbidden IP networks.
    
    Raises:
        SSRFSecurityError: If URL is malformed, has non-http scheme, or resolves to a private/restricted IP.
    Returns:
        (hostname, list_of_validated_ips)
    """
    guard = get_acquisition_ssrf_guard()
    return guard.validate_url(url)


def is_safe_acquisition_target(url: str) -> bool:
    """
    Non-raising predicate checking whether a target URL passes SSRF validation.
    """
    try:
        validate_acquisition_url(url)
        return True
    except (SSRFSecurityError, Exception) as e:
        logger.debug(f"Target URL '{url}' failed acquisition safety check: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SSRF-Protected Robots.txt Policy Engine
# ─────────────────────────────────────────────────────────────────────────────
class SafeRobotsPolicyEngine:
    """
    In-memory, TTL-cached, SSRF-guarded robots.txt parser.
    Ensures robots.txt fetches themselves pass SSRF validation.
    """

    def __init__(self, cache_ttl_seconds: int = 3600):
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache: Dict[str, Tuple[datetime, urllib.robotparser.RobotFileParser]] = {}
        self._lock = asyncio.Lock()

    async def can_fetch(
        self,
        url: str,
        user_agent: str = "TechNewsScrapper/7.0",
        respect_robots: bool = True,
    ) -> bool:
        """
        Check whether the given URL is allowed by the host's robots.txt policy.
        Returns True if robots compliance is disabled, if robots allows crawling,
        or if robots.txt is unavailable (404/network error).
        """
        if not respect_robots:
            return True

        if not is_safe_acquisition_target(url):
            return False

        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not domain:
            return False

        now = datetime.now(UTC)

        async with self._lock:
            if domain in self._cache:
                timestamp, parser = self._cache[domain]
                if now - timestamp < self.cache_ttl:
                    return parser.can_fetch(user_agent, url)

        # Build robots.txt URL
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        parser = urllib.robotparser.RobotFileParser()

        try:
            client = get_safe_http_client()
            res = await client.fetch(robots_url, timeout=5.0)
            if res.get("status") == 200 and res.get("content"):
                lines = res["content"].splitlines()
                parser.parse(lines)
            else:
                # If robots.txt returns 404 or empty, allow all
                parser.allow_all = True
        except Exception as e:
            logger.debug(f"Could not fetch robots.txt for {domain} safely ({e}); allowing fetch.")
            parser.allow_all = True

        async with self._lock:
            self._cache[domain] = (now, parser)

        return parser.can_fetch(user_agent, url)

    def clear_cache(self) -> None:
        """Clear cached robots policies."""
        self._cache.clear()


# Shared robots policy engine singleton
_global_robots_engine = SafeRobotsPolicyEngine()


def get_robots_policy_engine() -> SafeRobotsPolicyEngine:
    """Return the global robots policy engine."""
    return _global_robots_engine


async def can_fetch_robots(url: str, user_agent: str = "TechNewsScrapper/7.0") -> bool:
    """
    Check robots.txt compliance for a target URL safely.
    """
    engine = get_robots_policy_engine()
    return await engine.can_fetch(url, user_agent=user_agent)


# ─────────────────────────────────────────────────────────────────────────────
# Authoritative Safe Acquisition Client
# ─────────────────────────────────────────────────────────────────────────────
class SafeAcquisitionClient:
    """
    High-level authoritative acquisition client composing:
    - Pre-flight SSRF validation
    - Multi-hop redirect validation
    - Robots.txt compliance check
    - Response size limits and decompression bounding
    - Strict TLS verification
    """

    def __init__(
        self,
        guard: Optional[SSRFGuard] = None,
        fetch_policy: Optional[FetchPolicy] = None,
        robots_engine: Optional[SafeRobotsPolicyEngine] = None,
    ):
        self.guard = guard or get_acquisition_ssrf_guard()
        self.fetch_policy = fetch_policy or FetchPolicy()
        self.robots_engine = robots_engine or get_robots_policy_engine()
        self._client = SafeHttpClient(guard=self.guard)

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        timeout: Optional[float] = None,
        check_robots: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute an authoritative safe acquisition request.
        
        Raises:
            SSRFSecurityError: If URL or redirect target violates SSRF policy.
            PayloadSizeLimitExceeded: If response size exceeds configured threshold.
            PermissionError: If blocked by host robots.txt policy.
        """
        # 1. Pre-flight SSRF check
        self.guard.validate_url(url)

        # 2. Robots policy check
        if check_robots and self.fetch_policy.respect_robots_txt:
            allowed = await self.robots_engine.can_fetch(
                url,
                user_agent=self.fetch_policy.user_agent,
                respect_robots=True,
            )
            if not allowed:
                raise PermissionError(f"Target URL '{url}' is forbidden by robots.txt policy")

        # 3. Build headers with conditional tokens
        req_headers = self.fetch_policy.with_conditional_headers(etag=etag, last_modified=last_modified)
        if headers:
            req_headers.update(headers)

        req_timeout = timeout or self.fetch_policy.total_timeout

        # 4. Fetch via SafeHttpClient (per-hop SSRF validation & size bounding)
        return await self._client.fetch(
            url=url,
            method=method,
            headers=req_headers,
            timeout=req_timeout,
        )
