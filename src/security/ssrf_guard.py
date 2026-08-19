"""
SSRF Protection Gateway and Safe Network Client for Tech News Scrapper.
Location: src/security/ssrf_guard.py

Multi-layer outbound defense against Server-Side Request Forgery (SSRF),
DNS rebinding, internal network scanning, decompression bombs, and redirect hijacking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import logging
import socket
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urljoin
import zlib
import gzip

logger = logging.getLogger(__name__)


class SSRFSecurityError(Exception):
    """Raised when an outbound URL or IP violates security policies."""
    pass


class PayloadSizeLimitExceeded(SSRFSecurityError):
    """Raised when a response body exceeds configured size thresholds."""
    pass


@dataclass(frozen=True, slots=True)
class SSRFConfig:
    """Configuration for SSRFGuard."""
    allowed_schemes: Tuple[str, ...] = ("http", "https")
    max_redirects: int = 5
    max_raw_bytes: int = 10 * 1024 * 1024       # 10 MB raw network cap
    max_decompressed_bytes: int = 10 * 1024 * 1024 # 10 MB decompressed payload cap
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    total_timeout: float = 15.0
    dns_cache_ttl: float = 60.0


class SSRFGuard:
    """
    Validates outbound target URLs and resolved IP addresses against private,
    loopback, link-local, cloud metadata, and reserved networks.
    """

    # Forbidden IPv4 networks
    DENIED_IPV4_NETWORKS: Tuple[ipaddress.IPv4Network, ...] = (
        ipaddress.IPv4Network("0.0.0.0/8"),         # "This host on this network"
        ipaddress.IPv4Network("10.0.0.0/8"),        # Private-Use (RFC 1918)
        ipaddress.IPv4Network("100.64.0.0/10"),     # Shared Address Space / CGNAT
        ipaddress.IPv4Network("127.0.0.0/8"),       # Loopback
        ipaddress.IPv4Network("169.254.0.0/16"),    # Link-Local & Cloud Metadata (169.254.169.254)
        ipaddress.IPv4Network("172.16.0.0/12"),     # Private-Use (RFC 1918)
        ipaddress.IPv4Network("192.0.0.0/24"),      # IETF Protocol Assignments
        ipaddress.IPv4Network("192.0.2.0/24"),      # Documentation (TEST-NET-1)
        ipaddress.IPv4Network("192.168.0.0/16"),    # Private-Use (RFC 1918)
        ipaddress.IPv4Network("198.18.0.0/15"),     # Benchmarking
        ipaddress.IPv4Network("198.51.100.0/24"),   # Documentation (TEST-NET-2)
        ipaddress.IPv4Network("203.0.113.0/24"),    # Documentation (TEST-NET-3)
        ipaddress.IPv4Network("224.0.0.0/4"),       # Multicast
        ipaddress.IPv4Network("240.0.0.0/4"),       # Reserved for Future Use
        ipaddress.IPv4Network("255.255.255.255/32"), # Limited Broadcast
    )

    # Forbidden IPv6 networks
    DENIED_IPV6_NETWORKS: Tuple[ipaddress.IPv6Network, ...] = (
        ipaddress.IPv6Network("::1/128"),           # Loopback
        ipaddress.IPv6Network("::/128"),            # Unspecified
        ipaddress.IPv6Network("::ffff:0:0/96"),     # IPv4-mapped IPv6
        ipaddress.IPv6Network("64:ff9b::/96"),      # IPv4/IPv6 translation
        ipaddress.IPv6Network("100::/64"),          # Discard-Only Address Block
        ipaddress.IPv6Network("2001::/23"),         # IETF Protocol Assignments
        ipaddress.IPv6Network("2001:db8::/32"),     # Documentation
        ipaddress.IPv6Network("2002::/16"),         # 6to4
        ipaddress.IPv6Network("fc00::/7"),          # Unique Local (ULA)
        ipaddress.IPv6Network("fe80::/10"),         # Link-Local Unicast
        ipaddress.IPv6Network("ff00::/8"),          # Multicast
    )

    def __init__(self, config: Optional[SSRFConfig] = None):
        self.config = config or SSRFConfig()

    def is_ip_allowed(self, ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Tuple[bool, Optional[str]]:
        """
        Check if an IP address is safe for outbound connections.
        Returns (is_allowed, reason_if_blocked).
        """
        # If IPv4-mapped or NAT64 translated address, validate the embedded IPv4 address
        if isinstance(ip_obj, ipaddress.IPv6Address):
            if ip_obj in ipaddress.IPv6Network("::ffff:0:0/96") or ip_obj in ipaddress.IPv6Network("64:ff9b::/96"):
                embedded_v4 = ipaddress.IPv4Address(ip_obj.packed[-4:])
                return self.is_ip_allowed(embedded_v4)

        if ip_obj.is_loopback:
            return False, f"Loopback address forbidden: {ip_obj}"
        if ip_obj.is_private:
            return False, f"Private network address forbidden: {ip_obj}"
        if ip_obj.is_link_local:
            return False, f"Link-local address forbidden: {ip_obj}"
        if ip_obj.is_multicast:
            return False, f"Multicast address forbidden: {ip_obj}"
        if ip_obj.is_reserved:
            return False, f"Reserved address forbidden: {ip_obj}"
        if ip_obj.is_unspecified:
            return False, f"Unspecified address forbidden: {ip_obj}"

        if isinstance(ip_obj, ipaddress.IPv4Address):
            for net in self.DENIED_IPV4_NETWORKS:
                if ip_obj in net:
                    return False, f"IPv4 address in restricted network {net}: {ip_obj}"
        elif isinstance(ip_obj, ipaddress.IPv6Address):
            for net in self.DENIED_IPV6_NETWORKS:
                if ip_obj in net:
                    return False, f"IPv6 address in restricted network {net}: {ip_obj}"

        return True, None

    def resolve_and_validate_hostname(self, hostname: str) -> List[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """
        Resolve hostname to all IP addresses and validate EVERY returned address.
        If ANY address is in a forbidden range, raises SSRFSecurityError.
        """
        try:
            # First check if hostname is already a direct IP literal
            ip_literal = ipaddress.ip_address(hostname)
            allowed, reason = self.is_ip_allowed(ip_literal)
            if not allowed:
                raise SSRFSecurityError(f"Direct IP literal rejected: {reason}")
            return [ip_literal]
        except ValueError:
            pass  # Hostname is a domain name, proceed to DNS resolution

        try:
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise SSRFSecurityError(f"DNS resolution failed for hostname '{hostname}': {e}") from e

        if not addr_info:
            raise SSRFSecurityError(f"DNS resolution returned no addresses for hostname '{hostname}'")

        resolved_ips: List[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                resolved_ips.append(ip_obj)
                allowed, reason = self.is_ip_allowed(ip_obj)
                if not allowed:
                    raise SSRFSecurityError(
                        f"SSRF blocked: Hostname '{hostname}' resolved to prohibited IP '{ip_str}' ({reason})"
                    )
            except ValueError as e:
                raise SSRFSecurityError(f"Invalid IP address returned by DNS: '{ip_str}': {e}") from e

        return resolved_ips

    def validate_url(self, url: str) -> Tuple[str, List[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
        """
        Validate URL scheme and hostname. Returns (hostname, validated_ips).
        Raises SSRFSecurityError on any violation.
        """
        if not url or not isinstance(url, str):
            raise SSRFSecurityError("URL must be a non-empty string")

        parsed = urlparse(url.strip())
        if not parsed.scheme:
            raise SSRFSecurityError(f"Missing URL scheme in '{url}'")

        scheme = parsed.scheme.lower()
        if scheme not in self.config.allowed_schemes:
            raise SSRFSecurityError(f"Prohibited URL scheme '{scheme}'. Allowed: {self.config.allowed_schemes}")

        hostname = parsed.hostname
        if not hostname:
            raise SSRFSecurityError(f"Missing hostname in URL '{url}'")

        # Validate hostname & resolve IPs
        validated_ips = self.resolve_and_validate_hostname(hostname)
        return hostname, validated_ips


class SafeHttpClient:
    """
    Async HTTP client that enforces SSRF guard validation on the initial URL
    and on every single hop of any redirect chain, while bounding decompression.
    """

    def __init__(self, guard: Optional[SSRFGuard] = None):
        self.guard = guard or SSRFGuard()

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Fetch URL safely with per-hop redirect validation and response size bounding.
        """
        import aiohttp

        current_url = url
        redirect_count = 0
        visited_urls: Set[str] = {current_url}
        headers = headers or {"User-Agent": "TechNewsScrapper/7.0 (SSRF-Protected Acquisition)"}
        total_timeout = timeout or self.guard.config.total_timeout

        timeout_ctx = aiohttp.ClientTimeout(
            total=total_timeout,
            connect=self.guard.config.connect_timeout,
            sock_read=self.guard.config.read_timeout,
        )

        async with aiohttp.ClientSession(timeout=timeout_ctx) as session:
            while True:
                # Validate current URL before request
                self.guard.validate_url(current_url)

                try:
                    async with session.request(
                        method=method,
                        url=current_url,
                        headers=headers,
                        allow_redirects=False,  # We handle redirects manually for security
                    ) as resp:
                        # Check for redirect (301, 302, 303, 307, 308)
                        if resp.status in (301, 302, 303, 307, 308):
                            redirect_count += 1
                            if redirect_count > self.guard.config.max_redirects:
                                raise SSRFSecurityError(
                                    f"Exceeded max redirects ({self.guard.config.max_redirects}) for URL '{url}'"
                                )

                            location = resp.headers.get("Location")
                            if not location:
                                raise SSRFSecurityError(f"Redirect status {resp.status} with missing Location header")

                            next_url = urljoin(current_url, location)
                            if next_url in visited_urls:
                                raise SSRFSecurityError(f"Redirect loop detected: '{next_url}'")

                            visited_urls.add(next_url)
                            current_url = next_url
                            continue

                        # Check declared Content-Length if present
                        content_length = resp.headers.get("Content-Length")
                        if content_length:
                            try:
                                if int(content_length) > self.guard.config.max_raw_bytes:
                                    raise PayloadSizeLimitExceeded(
                                        f"Content-Length {content_length} exceeds maximum cap of {self.guard.config.max_raw_bytes} bytes"
                                    )
                            except ValueError:
                                pass

                        # Stream response body and count raw/decompressed bytes
                        raw_bytes = bytearray()
                        decompressed_size = 0
                        is_gzip = "gzip" in resp.headers.get("Content-Encoding", "").lower()
                        is_deflate = "deflate" in resp.headers.get("Content-Encoding", "").lower()
                        
                        decompressor = None
                        if is_gzip:
                            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                        elif is_deflate:
                            decompressor = zlib.decompressobj(-zlib.MAX_WBITS)

                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            raw_bytes.extend(chunk)
                            if len(raw_bytes) > self.guard.config.max_raw_bytes:
                                raise PayloadSizeLimitExceeded(
                                    f"Raw response exceeded cap of {self.guard.config.max_raw_bytes} bytes"
                                )

                            if decompressor:
                                try:
                                    decompressed_chunk = decompressor.decompress(chunk)
                                    decompressed_size += len(decompressed_chunk)
                                    if decompressed_size > self.guard.config.max_decompressed_bytes:
                                        raise PayloadSizeLimitExceeded(
                                            f"Decompressed payload exceeded cap of {self.guard.config.max_decompressed_bytes} bytes"
                                        )
                                except zlib.error:
                                    pass # Let final parser handle raw bytes

                        # Decode text safely
                        encoding = resp.charset or "utf-8"
                        try:
                            text = raw_bytes.decode(encoding, errors="replace")
                        except Exception:
                            text = raw_bytes.decode("utf-8", errors="replace")

                        return {
                            "status": resp.status,
                            "final_url": str(resp.url),
                            "headers": dict(resp.headers),
                            "content": text,
                            "raw_bytes": bytes(raw_bytes),
                            "redirects_followed": redirect_count,
                        }

                except aiohttp.ClientError as e:
                    raise SSRFSecurityError(f"HTTP request error fetching '{current_url}': {e}") from e
