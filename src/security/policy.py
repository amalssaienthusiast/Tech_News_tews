"""
Security Policy — Single source of truth for API security configuration.

Consumed by both the aiohttp engine server (main_engine.py) and the FastAPI
gateway (src/api/app.py) to ensure a single, unified security boundary.

This module provides:
  - CORS origin validation and header generation
  - API key verification (SHA-256 hashed keys)
  - Rate limiting with tiered daily limits
  - Rate-limit response headers (X-RateLimit-*)
  - Public path configuration

Phase 1A Task 1A.2 — created as part of Security P0 Remediation.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CORS Policy
# ─────────────────────────────────────────────────────────────────────────────

def _load_allowed_origins() -> list[str]:
    """Load CORS allowed origins from environment.

    Reads SECURITY_CORS_ORIGINS (preferred) or API_CORS_ORIGINS (legacy compat).
    Falls back to localhost defaults for development.
    """
    raw = os.getenv(
        "SECURITY_CORS_ORIGINS",
        os.getenv("API_CORS_ORIGINS", "http://localhost,http://127.0.0.1"),
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


ALLOWED_ORIGINS: list[str] = _load_allowed_origins()


def is_origin_allowed(origin: Optional[str]) -> bool:
    """Check whether the given Origin header is in the configured allowlist."""
    if not origin:
        return False
    return origin in ALLOWED_ORIGINS


def cors_headers(origin: Optional[str]) -> dict[str, str]:
    """Return CORS response headers for an allowed origin.

    Returns an empty dict if the origin is not allowed (the caller should
    not set any Access-Control-Allow-Origin header in that case).
    """
    if not is_origin_allowed(origin):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
        "Access-Control-Max-Age": "86400",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public paths (no authentication required)
# ─────────────────────────────────────────────────────────────────────────────

PUBLIC_PATHS: frozenset[str] = frozenset({
    # Engine paths
    "/api/v1/health",
    # FastAPI paths
    "/health",
    "/health/detailed",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
})


def is_public_path(path: str) -> bool:
    """Return True if the request path does not require authentication."""
    return path in PUBLIC_PATHS


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting (in-memory, per-process)
# ─────────────────────────────────────────────────────────────────────────────

API_TIERS: dict[str, dict] = {
    "free":  {"daily_limit": 1000,   "description": "Free tier — 1,000 requests/day"},
    "basic": {"daily_limit": 10_000, "description": "Basic tier — 10k requests/day"},
    "pro":   {"daily_limit": 100_000, "description": "Pro tier — 100k requests/day"},
}


class RateLimiter:
    """Simple in-memory per-API-key daily rate limiter.

    For multi-worker deployments (gunicorn --workers N), each worker has its
    own counter — effective limit becomes N × daily_limit.  For strict limits,
    swap for a Redis-backed implementation.
    """

    def __init__(self) -> None:
        self._requests: dict[str, dict] = {}

    def check_limit(self, api_key: str, tier: str) -> bool:
        """Return True if the request is within rate limits."""
        limit = API_TIERS.get(tier, API_TIERS["free"])["daily_limit"]
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{api_key}:{today}"
        if key not in self._requests or self._requests[key]["date"] != today:
            self._requests[key] = {"count": 0, "date": today}
        if self._requests[key]["count"] >= limit:
            return False
        self._requests[key]["count"] += 1
        return True

    def get_remaining(self, api_key: str, tier: str) -> int:
        """Return remaining requests for the current day."""
        limit = API_TIERS.get(tier, API_TIERS["free"])["daily_limit"]
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{api_key}:{today}"
        if key not in self._requests:
            return int(limit)
        return max(0, int(limit - self._requests[key].get("count", 0)))

    def get_reset_timestamp(self) -> str:
        """Return the ISO timestamp when the current rate-limit window resets (midnight UTC)."""
        now = datetime.now(UTC)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # If we're already past midnight, the next reset is tomorrow
        if tomorrow <= now:
            from datetime import timedelta
            tomorrow += timedelta(days=1)
        return tomorrow.isoformat()


# Shared singleton
rate_limiter = RateLimiter()


def get_reset_seconds() -> int:
    """Return seconds remaining until rate-limit window resets at midnight UTC."""
    now = datetime.now(UTC)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if tomorrow <= now:
        from datetime import timedelta
        tomorrow += timedelta(days=1)
    return max(1, int((tomorrow - now).total_seconds()))


def rate_limit_headers(api_key: str, tier: str, is_limited: bool = False) -> dict[str, str]:
    """Generate standard rate-limit response headers, including Retry-After when limited."""
    limit = API_TIERS.get(tier, API_TIERS["free"])["daily_limit"]
    remaining = rate_limiter.get_remaining(api_key, tier)
    reset = rate_limiter.get_reset_timestamp()
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": reset,
    }
    if is_limited or remaining == 0:
        headers["Retry-After"] = str(get_reset_seconds())
    return headers


# ─────────────────────────────────────────────────────────────────────────────
# API key verification (SHA-256)
# ─────────────────────────────────────────────────────────────────────────────

# Optional: a simple bearer-token mode for the engine API.
# When ENGINE_API_KEY is set, the engine requires X-API-Key to match.
# When unset, the engine falls back to the database-backed APIKeyManager
# from src/api/app.py (for the FastAPI surface).

_ENGINE_API_KEY: Optional[str] = os.getenv("ENGINE_API_KEY")


def verify_engine_api_key(provided_key: Optional[str]) -> bool:
    """Verify an API key against the engine's configured key.

    Returns True if:
      - The provided key matches ENGINE_API_KEY (constant-time comparison)
      - ENGINE_API_KEY is not set AND not in production environment (local dev fallback)

    Returns False if:
      - In production and ENGINE_API_KEY is not set (fails closed)
      - Provided key is missing or does not match ENGINE_API_KEY
    """
    engine_key = os.getenv("ENGINE_API_KEY") or _ENGINE_API_KEY
    is_prod = (
        os.getenv("TECHNEWS_ENV", "").lower() in ("production", "prod")
        or os.getenv("ENV", "").lower() in ("production", "prod")
    )

    if not engine_key:
        if is_prod:
            logger.error("ENGINE_API_KEY is not configured in production. Request rejected (fails closed).")
            return False
        # Development fallback only
        return True

    if not provided_key:
        return False
    # Constant-time comparison to prevent timing attacks
    return secrets.compare_digest(provided_key, engine_key)


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256 for at-rest storage."""
    return hashlib.sha256(key.encode()).hexdigest()
