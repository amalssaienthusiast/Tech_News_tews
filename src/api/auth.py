"""
API Authentication & Rate Limiting Dependencies.
Location: src/api/auth.py
"""

from __future__ import annotations

from datetime import datetime, UTC
import hashlib
import logging
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Optional

from fastapi import Header, HTTPException

from src.security.policy import (
    RateLimiter,
    rate_limit_headers as policy_rate_limit_headers,
)

logger = logging.getLogger(__name__)

ALLOW_ANONYMOUS_API = os.getenv("API_ALLOW_ANONYMOUS", "false").lower() == "true"
rate_limiter = RateLimiter()


class APIKeyManager:
    """Manages API key validation, creation, and tier lookup.

    Keys are stored as SHA-256 hashes in the api_keys table.
    """

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self._db_path = Path(db_path) if db_path else None
        self._ensure_schema()

    def _get_connection(self):
        if self._db_path is not None:
            db_path = self._db_path
        else:
            from config.settings import DB_FILE
            db_path = DB_FILE
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        key_id TEXT PRIMARY KEY,
                        key_hash TEXT NOT NULL UNIQUE,
                        user_id TEXT,
                        tier TEXT DEFAULT 'free',
                        name TEXT,
                        created_at TEXT,
                        last_used TEXT,
                        enabled INTEGER DEFAULT 1
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to create api_keys schema: {e}")
            raise

    def validate_key(self, api_key: str) -> Optional[dict]:
        if not api_key:
            return None
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM api_keys WHERE key_hash = ? AND enabled = 1",
                    (key_hash,),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                        (datetime.now(UTC).isoformat(), key_hash),
                    )
                    conn.commit()
                    return {
                        "key_id": row["key_id"],
                        "tier": row["tier"],
                        "user_id": row["user_id"],
                    }
        except Exception as e:
            logger.error(f"API key validation error: {e}")
        return None

    def create_key(self, user_id: str, tier: str = "free", name: str = "") -> str:
        """Create a new API key. Returns plaintext key once."""
        api_key = f"tns_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_id = secrets.token_hex(8)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO api_keys (key_id, key_hash, user_id, tier, name, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (key_id, key_hash, user_id, tier, name, datetime.now(UTC).isoformat()),
                )
                conn.commit()
            return api_key
        except Exception as e:
            logger.error(f"Failed to create API key: {e}")
            return ""


api_key_manager = APIKeyManager()


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Verify API key and apply rate limiting.

    Raises 401 if no key and anonymous mode is disabled.
    Raises 429 if rate limit exceeded.
    """
    if not x_api_key:
        if not ALLOW_ANONYMOUS_API:
            raise HTTPException(
                status_code=401,
                detail="API key required. Provide X-API-Key header or set API_ALLOW_ANONYMOUS=true for local development.",
            )
        if not rate_limiter.check_limit("anonymous", "free"):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please add an API key for higher limits.",
                headers=policy_rate_limit_headers("anonymous", "free", is_limited=True),
            )
        return {"tier": "free", "anonymous": True}

    # 1. Check environment RBAC auth manager (TECHNEWS_ADMIN_API_KEY, TECHNEWS_RW_API_KEY, TECHNEWS_RO_API_KEY)
    try:
        from src.security.middleware import get_auth_manager
        from src.security.models import Role
        auth_mgr = get_auth_manager()
        principal = auth_mgr.authenticate_key(x_api_key)
        if principal:
            tier_map = {Role.ADMIN: "pro", Role.READ_WRITE: "basic", Role.READ_ONLY: "free"}
            tier = tier_map.get(principal.role, "free")
            if not rate_limiter.check_limit(x_api_key, tier):
                remaining = rate_limiter.get_remaining(x_api_key, tier)
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Remaining: {remaining}. Upgrade tier for higher limits.",
                    headers=policy_rate_limit_headers(x_api_key, tier, is_limited=True),
                )
            return {
                "key_id": principal.api_key_fingerprint,
                "tier": tier,
                "user_id": principal.identity,
                "role": principal.role.value,
            }
    except Exception as e:
        logger.debug(f"EnvAuthManager lookup skipped: {e}")

    # 2. Check Database-backed APIKeyManager
    key_info = api_key_manager.validate_key(x_api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not rate_limiter.check_limit(x_api_key, key_info["tier"]):
        remaining = rate_limiter.get_remaining(x_api_key, key_info["tier"])
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Remaining: {remaining}. Upgrade tier for higher limits.",
            headers=policy_rate_limit_headers(x_api_key, key_info["tier"], is_limited=True),
        )
    return key_info
