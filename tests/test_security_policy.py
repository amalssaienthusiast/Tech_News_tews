"""
Tests for shared SecurityPolicy — Phase 1A Task 1A.2.

Covers:
  - CORS origin validation (allowed/rejected)
  - API key verification (missing/malformed/wrong/correct)
  - Rate limiting and headers
  - Public path identification
"""

import os
import pytest
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# SecurityPolicy unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCORSPolicy:
    """CORS origin allowlist enforcement."""

    def test_allowed_origin_returns_headers(self):
        from src.security.policy import cors_headers
        headers = cors_headers("http://localhost")
        assert "Access-Control-Allow-Origin" in headers
        assert headers["Access-Control-Allow-Origin"] == "http://localhost"

    def test_rejected_origin_returns_empty(self):
        from src.security.policy import cors_headers
        headers = cors_headers("http://evil.example.com")
        assert headers == {}

    def test_none_origin_returns_empty(self):
        from src.security.policy import cors_headers
        headers = cors_headers(None)
        assert headers == {}

    def test_wildcard_never_returned(self):
        """Wildcard CORS must never be produced by the security policy."""
        from src.security.policy import cors_headers, ALLOWED_ORIGINS
        for origin in ALLOWED_ORIGINS:
            headers = cors_headers(origin)
            assert headers.get("Access-Control-Allow-Origin") != "*"

    def test_is_origin_allowed_true(self):
        from src.security.policy import is_origin_allowed
        assert is_origin_allowed("http://localhost") is True

    def test_is_origin_allowed_false(self):
        from src.security.policy import is_origin_allowed
        assert is_origin_allowed("http://attacker.com") is False


class TestAPIKeyVerification:
    """Engine API key verification."""

    def test_no_engine_key_configured_allows_all(self):
        """When ENGINE_API_KEY is unset, dev mode allows all requests."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove ENGINE_API_KEY if set
            os.environ.pop("ENGINE_API_KEY", None)
            # Reimport to pick up env change
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)
            assert policy_mod.verify_engine_api_key(None) is True
            assert policy_mod.verify_engine_api_key("anything") is True

    def test_engine_key_configured_rejects_missing(self):
        """When ENGINE_API_KEY is set, missing key is rejected."""
        with patch.dict(os.environ, {"ENGINE_API_KEY": "test-secret-key-123"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)
            assert policy_mod.verify_engine_api_key(None) is False
            assert policy_mod.verify_engine_api_key("") is False

    def test_engine_key_configured_rejects_wrong(self):
        """When ENGINE_API_KEY is set, wrong key is rejected."""
        with patch.dict(os.environ, {"ENGINE_API_KEY": "test-secret-key-123"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)
            assert policy_mod.verify_engine_api_key("wrong-key") is False

    def test_engine_key_configured_accepts_correct(self):
        """When ENGINE_API_KEY is set, correct key is accepted."""
        with patch.dict(os.environ, {"ENGINE_API_KEY": "test-secret-key-123"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)
            assert policy_mod.verify_engine_api_key("test-secret-key-123") is True


class TestPublicPaths:
    """Public path identification (no auth required)."""

    def test_health_is_public(self):
        from src.security.policy import is_public_path
        assert is_public_path("/api/v1/health") is True
        assert is_public_path("/health") is True

    def test_data_endpoints_are_not_public(self):
        from src.security.policy import is_public_path
        assert is_public_path("/api/v1/feed") is False
        assert is_public_path("/api/v1/sources") is False
        assert is_public_path("/api/v1/stream") is False

    def test_metrics_is_public(self):
        from src.security.policy import is_public_path
        assert is_public_path("/metrics") is True


class TestRateLimiting:
    """Rate limiter behavior and header generation."""

    def test_rate_limiter_allows_within_limit(self):
        from src.security.policy import RateLimiter
        limiter = RateLimiter()
        assert limiter.check_limit("test-key", "free") is True

    def test_rate_limiter_blocks_over_limit(self):
        from src.security.policy import RateLimiter
        limiter = RateLimiter()
        for _ in range(1000):
            limiter.check_limit("exhaust-key", "free")
        assert limiter.check_limit("exhaust-key", "free") is False

    def test_rate_limit_remaining_decrements(self):
        from src.security.policy import RateLimiter
        limiter = RateLimiter()
        initial = limiter.get_remaining("decrement-key", "free")
        limiter.check_limit("decrement-key", "free")
        after = limiter.get_remaining("decrement-key", "free")
        assert after == initial - 1

    def test_rate_limit_headers_contain_required_fields(self):
        from src.security.policy import rate_limit_headers
        headers = rate_limit_headers("header-test-key", "free")
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers
        assert headers["X-RateLimit-Limit"] == "1000"

    def test_rate_limit_headers_retry_after_when_limited(self):
        from src.security.policy import rate_limit_headers
        headers = rate_limit_headers("limited-key", "free", is_limited=True)
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) > 0


class TestHashAPIKey:
    """SHA-256 key hashing."""

    def test_hash_is_deterministic(self):
        from src.security.policy import hash_api_key
        h1 = hash_api_key("test-key")
        h2 = hash_api_key("test-key")
        assert h1 == h2

    def test_hash_is_hex_string(self):
        from src.security.policy import hash_api_key
        h = hash_api_key("test-key")
        assert len(h) == 64  # SHA-256 hex digest
        int(h, 16)  # Should not raise — valid hex


class TestEngineSecurityIntegration:
    """Integration test suite for engine server security middleware."""

    @pytest.fixture
    def app(self):
        from aiohttp import web
        from src.security.policy import (
            cors_headers,
            is_public_path,
            rate_limit_headers,
            rate_limiter,
            verify_engine_api_key,
        )

        app = web.Application()

        async def handle_health(request):
            return web.json_response({"status": "ok"})

        async def handle_feed(request):
            return web.json_response({"feed": []})

        async def handle_sources(request):
            return web.json_response({"sources": []})

        async def handle_stream(request):
            resp = web.StreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream"},
            )
            await resp.prepare(request)
            await resp.write(b"data: connected\n\n")
            return resp

        app.router.add_get("/api/v1/health", handle_health)
        app.router.add_get("/api/v1/feed", handle_feed)
        app.router.add_get("/api/v1/sources", handle_sources)
        app.router.add_get("/api/v1/stream", handle_stream)

        @web.middleware
        async def security_middleware(request, handler):
            origin = request.headers.get("Origin")

            if request.method == "OPTIONS":
                resp = web.Response()
                resp.headers.update(cors_headers(origin))
                return resp

            if not is_public_path(request.path):
                api_key = request.headers.get("X-API-Key")
                if not verify_engine_api_key(api_key):
                    return web.json_response(
                        {"error": "API key required. Provide X-API-Key header."},
                        status=401,
                    )
                key_id = api_key or "anonymous"
                if not rate_limiter.check_limit(key_id, "free"):
                    resp = web.json_response(
                        {"error": "Rate limit exceeded."},
                        status=429,
                    )
                    resp.headers.update(rate_limit_headers(key_id, "free", is_limited=True))
                    return resp

            resp = await handler(request)
            resp.headers.update(cors_headers(origin))
            if not is_public_path(request.path):
                api_key = request.headers.get("X-API-Key")
                if api_key:
                    resp.headers.update(rate_limit_headers(api_key, "free"))
            return resp

        app.middlewares.append(security_middleware)
        return app

    @pytest.fixture
    async def client(self, app):
        from aiohttp.test_utils import TestClient, TestServer
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        yield client
        await client.close()

    async def test_public_health_without_key(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

    async def test_missing_api_key_when_required(self, client):
        with patch.dict(os.environ, {"ENGINE_API_KEY": "secret-key"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)

            resp = await client.get("/api/v1/feed")
            assert resp.status == 401
            data = await resp.json()
            assert "error" in data

    async def test_wrong_api_key(self, client):
        with patch.dict(os.environ, {"ENGINE_API_KEY": "secret-key"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)

            resp = await client.get("/api/v1/feed", headers={"X-API-Key": "wrong-key"})
            assert resp.status == 401

    async def test_correct_api_key(self, client):
        with patch.dict(os.environ, {"ENGINE_API_KEY": "secret-key"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)

            resp = await client.get("/api/v1/feed", headers={"X-API-Key": "secret-key"})
            assert resp.status == 200
            assert "X-RateLimit-Limit" in resp.headers

    async def test_sse_without_key(self, client):
        with patch.dict(os.environ, {"ENGINE_API_KEY": "secret-key"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)

            resp = await client.get("/api/v1/stream")
            assert resp.status == 401

    async def test_sse_with_valid_key(self, client):
        with patch.dict(os.environ, {"ENGINE_API_KEY": "secret-key"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)

            resp = await client.get("/api/v1/stream", headers={"X-API-Key": "secret-key"})
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "text/event-stream"

    async def test_cors_allowed_origin(self, client):
        resp = await client.get("/api/v1/health", headers={"Origin": "http://localhost"})
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost"

    async def test_cors_rejected_origin(self, client):
        resp = await client.get("/api/v1/health", headers={"Origin": "http://attacker.com"})
        assert "Access-Control-Allow-Origin" not in resp.headers

    async def test_rate_limit_exceeded_returns_429_and_retry_after(self, client):
        from src.security.policy import rate_limiter
        for _ in range(1000):
            rate_limiter.check_limit("limited-engine-key", "free")

        with patch.dict(os.environ, {"ENGINE_API_KEY": "limited-engine-key"}):
            import importlib
            import src.security.policy as policy_mod
            importlib.reload(policy_mod)

            resp = await client.get("/api/v1/feed", headers={"X-API-Key": "limited-engine-key"})
            assert resp.status == 429
            assert "Retry-After" in resp.headers
            assert "X-RateLimit-Limit" in resp.headers

