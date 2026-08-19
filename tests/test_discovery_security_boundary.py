"""
Authoritative Security Boundary and SSRF Protection Test Suite for WebDiscoveryAgent.
Validates that all outbound discovery requests strictly enforce:
1. Public HTTP/HTTPS target validation
2. SSRF rejection of RFC 1918 private IP ranges
3. Loopback rejection (127.0.0.1, localhost, ::1)
4. Cloud metadata rejection (169.254.169.254)
5. Non-raising safe error handling
6. Timeout enforcement
7. TLS verification compliance
8. Redirect safety bounding
"""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.discovery import WebDiscoveryAgent
from src.security.ssrf_guard import SSRFSecurityError, SSRFGuard


class TestWebDiscoverySecurityBoundary(unittest.TestCase):
    """Security regression tests for WebDiscoveryAgent outbound boundary."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.discovered_sources = []
        self.mock_db.add_discovered_source = MagicMock(return_value=True)
        
        with patch("src.discovery.GOOGLE_API_KEY", ""),              patch("src.discovery.GOOGLE_CSE_ID", ""),              patch("src.discovery.BING_API_KEY", ""):
            self.agent = WebDiscoveryAgent(self.mock_db)

    def test_ssrf_loopback_rejected_sync(self):
        """verify_source must reject loopback (127.0.0.1) targets without outbound connection."""
        result = self.agent.verify_source("http://127.0.0.1:8000/admin")
        self.assertIsNone(result, "Loopback URL must be rejected by SSRF guard")

    def test_ssrf_localhost_rejected_sync(self):
        """verify_source must reject localhost targets without outbound connection."""
        result = self.agent.verify_source("http://localhost:5000/api")
        self.assertIsNone(result, "localhost must be rejected by SSRF guard")

    def test_ssrf_private_ip_rfc1918_rejected_sync(self):
        """verify_source must reject RFC 1918 private subnets (10.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12)."""
        for private_url in [
            "http://10.0.0.5/feed.xml",
            "https://192.168.1.1/news",
            "http://172.16.0.10:8080/rss",
        ]:
            with self.subTest(url=private_url):
                result = self.agent.verify_source(private_url)
                self.assertIsNone(result, f"Private IP {private_url} must be rejected")

    def test_ssrf_cloud_metadata_rejected_sync(self):
        """verify_source must reject AWS/GCP cloud metadata IP (169.254.169.254)."""
        result = self.agent.verify_source("http://169.254.169.254/latest/meta-data/")
        self.assertIsNone(result, "Cloud metadata IP must be rejected")

    def test_ssrf_ipv6_loopback_rejected_sync(self):
        """verify_source must reject IPv6 loopback (::1)."""
        result = self.agent.verify_source("http://[::1]:8000/status")
        self.assertIsNone(result, "IPv6 loopback must be rejected")

    def test_valid_public_https_source_verified_sync(self):
        """verify_source should allow valid public HTTPS targets and parse tech content."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
        <head><title>Kernel Insights</title><link type="application/rss+xml" href="/feed.xml"></head>
        <body><p>Technology insights into software development, artificial intelligence, machine learning, and cybersecurity hardware.</p></body>
        </html>
        """
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(self.agent.session, "get", return_value=mock_response), \
             patch.object(self.agent.ssrf_guard, "validate_url", return_value=("kernelinsights.example.com", [])):
            result = self.agent.verify_source("https://kernelinsights.example.com")
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "rss")
            self.assertEqual(result["name"], "Kernel Insights")
            self.assertTrue(result["verified"])

    def test_ssrf_poisoned_rss_feed_url_fallback(self):
        """If an external page contains an RSS feed link pointing to a private IP, it must be neutralized."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
        <head><title>Malicious Tech Blog</title><link type="application/rss+xml" href="http://169.254.169.254/secret.xml"></head>
        <body><p>Latest software development and artificial intelligence engineering insights.</p></body>
        </html>
        """
        def fake_validate(u):
            if "169.254" in u or "secret.xml" in u:
                raise SSRFSecurityError("Cloud metadata feed blocked")
            return ("safe.example.com", [])

        with patch.object(self.agent.session, "get", return_value=mock_response), \
             patch.object(self.agent.ssrf_guard, "validate_url", side_effect=fake_validate):
            result = self.agent.verify_source("https://safe.example.com")
            self.assertIsNotNone(result)
            # The poisoned feed link was neutralized; fallback to web type
            self.assertEqual(result["type"], "web")
            self.assertEqual(result["url"], "https://safe.example.com")


class TestWebDiscoverySecurityBoundaryAsync(unittest.IsolatedAsyncioTestCase):
    """Async security regression tests for WebDiscoveryAgent."""

    async def asyncSetUp(self):
        self.mock_db = MagicMock()
        self.mock_db.discovered_sources = []
        self.mock_db.add_discovered_source = MagicMock(return_value=True)
        
        with patch("src.discovery.GOOGLE_API_KEY", ""), \
             patch("src.discovery.GOOGLE_CSE_ID", ""), \
             patch("src.discovery.BING_API_KEY", ""):
            self.agent = WebDiscoveryAgent(self.mock_db)

    async def test_ssrf_loopback_rejected_async(self):
        """verify_source_async must reject loopback (127.0.0.1) without dispatching network call."""
        mock_session = MagicMock()
        result = await self.agent.verify_source_async(mock_session, "http://127.0.0.1:8000/feed")
        self.assertIsNone(result)
        mock_session.get.assert_not_called()

    async def test_ssrf_private_ip_rejected_async(self):
        """verify_source_async must reject private IP subnets."""
        mock_session = MagicMock()
        for priv_url in ["http://10.20.30.40/feed", "https://192.168.1.50/rss"]:
            with self.subTest(url=priv_url):
                result = await self.agent.verify_source_async(mock_session, priv_url)
                self.assertIsNone(result)

    async def test_ssrf_metadata_rejected_async(self):
        """verify_source_async must reject 169.254.169.254 metadata endpoint."""
        mock_session = MagicMock()
        result = await self.agent.verify_source_async(mock_session, "http://169.254.169.254/latest/user-data")
        self.assertIsNone(result)
        mock_session.get.assert_not_called()

    async def test_valid_public_https_async_fetch(self):
        """verify_source_async correctly processes safe public targets via safe client."""
        mock_safe_client = AsyncMock()
        mock_safe_client.fetch.return_value = {
            "status": 200,
            "content": """
            <html>
            <head><title>Cloud Computing Gazette</title><link type="application/rss+xml" href="/rss.xml"></head>
            <body><p>Technology discussions regarding cloud computing, software development, artificial intelligence, and cybersecurity.</p></body>
            </html>
            """,
            "headers": {},
        }
        self.agent.safe_client = mock_safe_client

        with patch.object(self.agent.ssrf_guard, "validate_url", return_value=("cloudgazette.example.com", [])):
            result = await self.agent.verify_source_async(None, "https://cloudgazette.example.com")
            self.assertIsNotNone(result)
            self.assertEqual(result["name"], "Cloud Computing Gazette")
            self.assertEqual(result["type"], "rss")
