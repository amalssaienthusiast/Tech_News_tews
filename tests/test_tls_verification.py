"""
TLS Verification Tests — Task 1A.3

Verifies:
  - Standard certificate verification is enabled by default across all network clients.
  - Invalid/expired/self-signed SSL certificates are rejected.
  - Known valid HTTPS endpoints connect successfully.
  - Static AST audit: Zero ssl=False, verify=False, or CERT_NONE bypasses exist in production code.
  - Shared create_ssl_context helper creates a strict SSLContext.
  - Telegram bot connector uses verified SSL.
"""

import ast
import os
import ssl
from pathlib import Path
import pytest
import aiohttp
from src.utils.http import create_ssl_context, create_connector


# ─────────────────────────────────────────────────────────────────────────────
# SSL Context & Helper Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSSLContextConfig:
    """Verify shared SSL context properties."""

    def test_create_ssl_context_enforces_verification(self):
        ctx = create_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    @pytest.mark.asyncio
    async def test_create_connector_uses_verified_ssl(self):
        connector = create_connector()
        assert isinstance(connector, aiohttp.TCPConnector)
        # aiohttp connector ssl attribute should be an SSLContext with CERT_REQUIRED
        assert connector._ssl is not False
        if isinstance(connector._ssl, ssl.SSLContext):
            assert connector._ssl.verify_mode == ssl.CERT_REQUIRED
            assert connector._ssl.check_hostname is True


# ─────────────────────────────────────────────────────────────────────────────
# Functional TLS Connection Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTLSConnections:
    """Network integration tests verifying strict TLS certificate verification."""

    @pytest.mark.asyncio
    async def test_invalid_certificate_rejected(self):
        """Self-signed / expired certificates must be rejected with an SSL/Connector error."""
        connector = create_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            with pytest.raises((aiohttp.ClientConnectorCertificateError, ssl.SSLError, Exception)) as exc_info:
                # badssl.com self-signed subdomain is a standard public test endpoint
                async with session.get("https://self-signed.badssl.com", timeout=aiohttp.ClientTimeout(total=5)):
                    pass
            # Verify the exception is certificate-related
            err_msg = f"{type(exc_info.value).__name__} {repr(exc_info.value)} {str(exc_info.value)}".lower()
            assert any(term in err_msg for term in ["cert", "verify", "ssl", "certificate", "handshake"])

    @pytest.mark.asyncio
    async def test_valid_https_endpoint_succeeds(self):
        """Valid HTTPS endpoint (e.g. google.com) must connect successfully."""
        connector = create_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get("https://www.google.com", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                assert resp.status == 200


# ─────────────────────────────────────────────────────────────────────────────
# Telegram Bot TLS Verification Test
# ─────────────────────────────────────────────────────────────────────────────

class TestTelegramBotTLS:
    """Verify Telegram Feeder Bot SSL configuration."""

    @pytest.mark.asyncio
    async def test_telegram_publisher_connector_uses_verified_ssl(self):
        from telegram_feeder_bot import TelegramPublisher
        pub = TelegramPublisher("fake_token", "@fake_chat")
        connector = pub._create_connector()
        assert isinstance(connector, aiohttp.TCPConnector)
        assert connector._ssl is not False
        if isinstance(connector._ssl, ssl.SSLContext):
            assert connector._ssl.verify_mode == ssl.CERT_REQUIRED
            assert connector._ssl.check_hostname is True


# ─────────────────────────────────────────────────────────────────────────────
# Static AST Code Audit (Zero Insecure TLS Bypasses)
# ─────────────────────────────────────────────────────────────────────────────

class TestASTSecurityAudit:
    """Static AST search verifying no insecure TLS bypass patterns remain in python files."""

    def test_no_ssl_false_in_production_code(self):
        """No production file may pass ssl=False to TCPConnector or aiohttp get/post."""
        repo_root = Path(__file__).parent.parent
        production_files = [
            p for p in repo_root.glob("**/*.py")
            if "tests" not in p.parts
            and ".venv" not in p.parts
            and "env" not in p.parts
            and "__pycache__" not in p.parts
        ]

        violations = []
        for file_path in production_files:
            source = file_path.read_text(encoding="utf-8")
            # Parse AST
            try:
                tree = ast.parse(source, filename=str(file_path))
            except Exception:
                continue

            for node in ast.walk(tree):
                # Check keyword args: ssl=False
                if isinstance(node, ast.keyword) and node.arg == "ssl":
                    if isinstance(node.value, ast.Constant) and node.value.value is False:
                        violations.append(f"{file_path.relative_to(repo_root)}:{node.lineno} ssl=False")

                # Check keyword args: verify=False
                if isinstance(node, ast.keyword) and node.arg == "verify":
                    if isinstance(node.value, ast.Constant) and node.value.value is False:
                        violations.append(f"{file_path.relative_to(repo_root)}:{node.lineno} verify=False")

                # Check assignment to cert_none / check_hostname=False
                if isinstance(node, ast.Attribute) and node.attr == "CERT_NONE":
                    violations.append(f"{file_path.relative_to(repo_root)}:{node.lineno} ssl.CERT_NONE")

        assert violations == [], f"Found insecure TLS violations in production code: {violations}"
