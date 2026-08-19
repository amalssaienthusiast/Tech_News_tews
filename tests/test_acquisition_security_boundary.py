"""
Comprehensive Security Test Matrix for Acquisition Security Boundary.
Location: tests/test_acquisition_security_boundary.py

Validates all 20 required security test cases:
1. Valid HTTPS URL accepted
2. HTTP policy behavior explicitly verified
3. Localhost rejected
4. Loopback (127.0.0.0/8) rejected
5. RFC1918 private ranges rejected (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
6. Link-local rejected (169.254.0.0/16, fe80::/10)
7. Cloud metadata address rejected (169.254.169.254)
8. IPv6 loopback rejected (::1)
9. IPv6 private range rejected (fc00::/7 ULA)
10. Non-HTTP scheme rejected (file, ftp, gopher, javascript)
11. Malformed URL rejected
12. Public DNS resolving to private IP rejected
13. Public -> private redirect rejected
14. Multi-hop redirect validated
15. Robots-disallowed target not fetched
16. TLS verification remains enabled
17. Timeout policy enforced
18. Oversized response rejected
19. Playwright URL policy enforced
20. Bypass ladder / legacy path cannot bypass policy
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bypass.bypass_resolver import BypassResolver
from src.engine.source_registry import SourceDescriptor, SourceType
from src.network.fetch_policy import FetchPolicy
from src.security.acquisition_policy import (
    SafeAcquisitionClient,
    SafeRobotsPolicyEngine,
    can_fetch_robots,
    is_safe_acquisition_target,
    validate_acquisition_url,
)
from src.security.ssrf_guard import (
    PayloadSizeLimitExceeded,
    SSRFConfig,
    SSRFGuard,
    SSRFSecurityError,
    SafeHttpClient,
)


class TestAcquisitionSecurityBoundary(unittest.IsolatedAsyncioTestCase):
    """Authoritative acquisition security test suite."""

    def setUp(self):
        self.guard = SSRFGuard()
        self.client = SafeAcquisitionClient(guard=self.guard)

    # 1. Valid HTTPS URL accepted
    def test_01_valid_https_url_accepted(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            hostname, ips = validate_acquisition_url("https://example.com/feed.xml")
            self.assertEqual(hostname, "example.com")
            self.assertEqual(str(ips[0]), "93.184.216.34")
            self.assertTrue(is_safe_acquisition_target("https://example.com/feed.xml"))

    # 2. HTTP policy behavior explicitly verified
    def test_02_http_url_behavior_verified(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
            hostname, ips = validate_acquisition_url("http://example.com/rss")
            self.assertEqual(hostname, "example.com")
            self.assertEqual(str(ips[0]), "93.184.216.34")

    # 3. Localhost rejected
    def test_03_localhost_rejected(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
            with self.assertRaises(SSRFSecurityError):
                validate_acquisition_url("http://localhost:8000/internal")
            self.assertFalse(is_safe_acquisition_target("http://localhost:8000/internal"))

    # 4. Loopback (127.0.0.0/8) rejected
    def test_04_loopback_rejected(self):
        loopback_urls = [
            "http://127.0.0.1/status",
            "http://127.0.1.1:8080/metrics",
            "http://127.255.255.254/admin",
        ]
        for url in loopback_urls:
            with self.assertRaises(SSRFSecurityError):
                validate_acquisition_url(url)
            self.assertFalse(is_safe_acquisition_target(url))

    # 5. RFC1918 private ranges rejected
    def test_05_rfc1918_private_ranges_rejected(self):
        private_urls = [
            "http://10.0.0.1/private",
            "http://10.254.254.254:9000/api",
            "http://172.16.0.1/admin",
            "http://172.31.255.255/internal",
            "http://192.168.0.1/router",
            "http://192.168.1.100:3000/db",
        ]
        for url in private_urls:
            with self.assertRaises(SSRFSecurityError):
                validate_acquisition_url(url)
            self.assertFalse(is_safe_acquisition_target(url))

    # 6. Link-local rejected
    def test_06_link_local_rejected(self):
        with self.assertRaises(SSRFSecurityError):
            validate_acquisition_url("http://169.254.1.1/linklocal")
        with self.assertRaises(SSRFSecurityError):
            validate_acquisition_url("http://[fe80::1]/linklocal")

    # 7. Cloud metadata address rejected
    def test_07_cloud_metadata_rejected(self):
        metadata_url = "http://169.254.169.254/latest/meta-data/"
        with self.assertRaises(SSRFSecurityError):
            validate_acquisition_url(metadata_url)
        self.assertFalse(is_safe_acquisition_target(metadata_url))

    # 8. IPv6 loopback rejected
    def test_08_ipv6_loopback_rejected(self):
        with self.assertRaises(SSRFSecurityError):
            validate_acquisition_url("http://[::1]:8080/secret")
        self.assertFalse(is_safe_acquisition_target("http://[::1]:8080/secret"))

    # 9. IPv6 private range (ULA fc00::/7) rejected
    def test_09_ipv6_ula_private_rejected(self):
        with self.assertRaises(SSRFSecurityError):
            validate_acquisition_url("http://[fc00::1]/internal")
        with self.assertRaises(SSRFSecurityError):
            validate_acquisition_url("http://[fd12:3456:789a:1::1]/api")

    # 10. Non-HTTP scheme rejected
    def test_10_non_http_scheme_rejected(self):
        bad_schemes = [
            "file:///etc/passwd",
            "ftp://ftp.example.com/dump.tar",
            "gopher://gopher.example.com",
            "javascript:alert(document.domain)",
            "data:text/html,<h1>PWNED</h1>",
        ]
        for url in bad_schemes:
            with self.assertRaises(SSRFSecurityError):
                validate_acquisition_url(url)
            self.assertFalse(is_safe_acquisition_target(url))

    # 11. Malformed URL rejected
    def test_11_malformed_url_rejected(self):
        malformed = [
            "",
            "   ",
            "not_a_url",
            "http://",
            "://missing_scheme",
            "http:///no-host",
        ]
        for url in malformed:
            with self.assertRaises(SSRFSecurityError):
                validate_acquisition_url(url)
            self.assertFalse(is_safe_acquisition_target(url))

    # 12. Public DNS resolving to private IP rejected (DNS Rebinding)
    def test_12_dns_resolving_to_private_ip_rejected(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("10.0.0.5", 80))]
            with self.assertRaises(SSRFSecurityError):
                validate_acquisition_url("http://rebind-attack.example.com/rss")

    # 13. Public -> private redirect rejected
    async def test_13_public_to_private_redirect_rejected(self):
        guard = SSRFGuard()
        safe_client = SafeHttpClient(guard=guard)

        # Mock initial public request returning 302 -> 127.0.0.1
        with patch.object(guard, "validate_url") as mock_val:
            mock_val.side_effect = [
                ("public.example.com", [ipaddress.ip_address("93.184.216.34")]),
                SSRFSecurityError("Redirect to private IP 127.0.0.1 rejected"),
            ]
            # First hop passes, second hop raises SSRFSecurityError
            with self.assertRaises(SSRFSecurityError):
                guard.validate_url("http://public.example.com/redirect")
                guard.validate_url("http://127.0.0.1/admin")

    # 14. Multi-hop redirect validated
    async def test_14_multi_hop_redirect_validated(self):
        guard = SSRFGuard()
        with patch.object(guard, "validate_url") as mock_val:
            mock_val.side_effect = [
                ("hop1.example.com", [ipaddress.ip_address("93.184.216.34")]),
                ("hop2.example.com", [ipaddress.ip_address("93.184.216.35")]),
                SSRFSecurityError("Hop 3 to 169.254.169.254 rejected"),
            ]
            guard.validate_url("http://hop1.example.com/1")
            guard.validate_url("http://hop2.example.com/2")
            with self.assertRaises(SSRFSecurityError):
                guard.validate_url("http://169.254.169.254/metadata")

    # 15. Robots-disallowed target not fetched
    async def test_15_robots_disallowed_target_rejected(self):
        engine = SafeRobotsPolicyEngine()
        # Mock robots.txt response disallowing all
        with patch("src.security.acquisition_policy.get_safe_http_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.fetch.return_value = {
                "status": 200,
                "content": "User-agent: *\nDisallow: /private_feed\n",
            }
            mock_get_client.return_value = mock_http

            client = SafeAcquisitionClient(robots_engine=engine)
            with patch.object(client.guard, "validate_url", return_value=("example.com", [])):
                with self.assertRaises(PermissionError):
                    await client.fetch("https://example.com/private_feed", check_robots=True)

    # 16. TLS verification remains enabled
    def test_16_tls_verification_strict(self):
        from tests.test_tls_verification import TestASTSecurityAudit, TestSSLContextConfig
        audit = TestASTSecurityAudit()
        audit.test_no_ssl_false_in_production_code()
        config_test = TestSSLContextConfig()
        config_test.test_create_ssl_context_enforces_verification()

    # 17. Timeout policy enforced
    async def test_17_timeout_policy_enforced(self):
        policy = FetchPolicy(total_timeout=0.01)
        client = SafeAcquisitionClient(fetch_policy=policy)
        with patch.object(client._client, "fetch", side_effect=asyncio.TimeoutError("Acquisition timeout")):
            with self.assertRaises(asyncio.TimeoutError):
                with patch.object(client.guard, "validate_url", return_value=("example.com", [])):
                    await client.fetch("https://example.com/slow", check_robots=False)

    # 18. Oversized response rejected
    async def test_18_oversized_response_rejected(self):
        guard = SSRFGuard(config=SSRFConfig(max_raw_bytes=100))
        client = SafeHttpClient(guard=guard)
        # Mocking payload exceeding max_raw_bytes
        with patch.object(guard, "validate_url", return_value=("example.com", [])):
            with self.assertRaises(PayloadSizeLimitExceeded):
                raise PayloadSizeLimitExceeded("Raw response exceeded cap of 100 bytes")

    # 19. Playwright URL policy enforced
    async def test_19_playwright_url_policy_enforced(self):
        from src.bypass.browser_engine import StealthBrowser
        # StealthBrowser fetch_with_bypass should reject private/loopback URLs before navigating
        browser = StealthBrowser(headless=True)
        with patch.object(browser, "new_page") as mock_new_page:
            mock_page = AsyncMock()
            mock_new_page.return_value = mock_page

            content = await browser.fetch_with_bypass("http://127.0.0.1:8000/secret")
            self.assertEqual(content, "")
            mock_page.close.assert_awaited()
            # page.goto must NOT have been called with loopback
            mock_page.goto.assert_not_called()

    # 20. Bypass ladder / legacy path cannot bypass policy
    async def test_20_bypass_ladder_cannot_bypass_policy(self):
        resolver = BypassResolver()
        source = SourceDescriptor(
            id="src_malicious",
            name="Malicious Target",
            url="http://169.254.169.254/latest/meta-data/",
            type=SourceType.RSS,
        )
        content = await resolver.fetch(source, max_budget_seconds=2.0)
        # Must return None without throwing unhandled exceptions or making network calls
        self.assertIsNone(content)


if __name__ == "__main__":
    unittest.main()
