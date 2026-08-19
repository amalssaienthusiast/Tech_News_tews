"""
Unit & Integration Tests for Production Security, RBAC, Rate Limiting & Headers (Subphase 6D).
Location: tests/test_api_security_hardened.py
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC, timedelta
from pathlib import Path
import unittest

from fastapi import Depends, FastAPI, Request, status
from fastapi.testclient import TestClient

from src.security.auth_manager import EnvAuthManager
from src.security.middleware import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    get_current_principal,
    require_role,
    require_scope,
    set_auth_manager,
    set_rate_limiter,
)
from src.security.models import (
    ApiKeyMetadata,
    Principal,
    Role,
    STANDARD_SCOPES,
    hash_key_fingerprint,
)
from src.security.rate_limiter import LocalTokenBucketLimiter

REPO_ROOT = Path(__file__).parent.parent


class TestSecurityHardened(unittest.TestCase):
    """Test suite for Phase 6D security controls."""

    def setUp(self):
        self.auth_mgr = EnvAuthManager()
        self.rate_limiter = LocalTokenBucketLimiter(
            role_quotas={
                Role.ADMIN: (10.0, 10.0),
                Role.READ_WRITE: (5.0, 5.0),
                Role.READ_ONLY: (2.0, 1.0),
                Role.ANONYMOUS: (2.0, 0.5),
            }
        )
        set_auth_manager(self.auth_mgr)
        set_rate_limiter(self.rate_limiter)

        # Build test application
        self.app = FastAPI()
        self.app.add_middleware(SecurityHeadersMiddleware)
        self.app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=1024 * 1024)  # 1MB test limit

        @self.app.get("/public")
        async def public_endpoint():
            return {"status": "ok"}

        @self.app.get("/read", dependencies=[Depends(require_role(Role.READ_ONLY))])
        async def read_endpoint(principal: Principal = Depends(get_current_principal)):
            return {"user": principal.identity, "role": principal.role.value}

        @self.app.post("/write", dependencies=[Depends(require_role(Role.READ_WRITE))])
        async def write_endpoint(request: Request, principal: Principal = Depends(get_current_principal)):
            body = await request.json()
            return {"written": True, "user": principal.identity}

        @self.app.post("/admin", dependencies=[Depends(require_role(Role.ADMIN))])
        async def admin_endpoint(principal: Principal = Depends(get_current_principal)):
            return {"admin": True, "user": principal.identity}

        @self.app.get("/scoped-event", dependencies=[Depends(require_scope("events:write"))])
        async def scoped_endpoint(principal: Principal = Depends(get_current_principal)):
            return {"scope": "events:write"}

        self.client = TestClient(self.app)

    def tearDown(self):
        set_auth_manager(None)
        set_rate_limiter(None)

    def test_security_headers_injected_and_modern_baseline(self):
        res = self.client.get("/public")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(res.headers["X-Frame-Options"], "DENY")
        self.assertEqual(res.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn("default-src 'self'", res.headers["Content-Security-Policy"])
        self.assertIn("Strict-Transport-Security", res.headers)
        # Ensure deprecated X-XSS-Protection is absent
        self.assertNotIn("X-XSS-Protection", res.headers)

    def test_request_body_size_limit_exceeded_returns_413(self):
        # 1MB limit in setup -> 1.5MB payload should return 413
        large_body = b"x" * (1500 * 1024)
        res = self.client.post("/public", content=large_body, headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(res.status_code, 413)

    def test_rbac_authorization_roles(self):
        # Register test keys
        admin_key = "admin-secret-key-12345"
        rw_key = "read-write-key-12345"
        ro_key = "read-only-key-12345"

        self.auth_mgr.register_key(admin_key, identity="root", role=Role.ADMIN)
        self.auth_mgr.register_key(rw_key, identity="editor", role=Role.READ_WRITE)
        self.auth_mgr.register_key(ro_key, identity="viewer", role=Role.READ_ONLY)

        # 1. Unauthenticated request to protected endpoint -> 401
        res_unauth = self.client.get("/read")
        self.assertEqual(res_unauth.status_code, 401)

        # 2. Read-only key can access /read
        res_ro = self.client.get("/read", headers={"Authorization": f"Bearer {ro_key}"})
        self.assertEqual(res_ro.status_code, 200)
        self.assertEqual(res_ro.json()["user"], "viewer")

        # 3. Read-only key cannot access /write -> 403 Forbidden
        res_ro_write = self.client.post("/write", json={"item": 1}, headers={"Authorization": f"Bearer {ro_key}"})
        self.assertEqual(res_ro_write.status_code, 403)

        # 4. Read-write key can access /write
        res_rw = self.client.post("/write", json={"item": 1}, headers={"Authorization": f"Bearer {rw_key}"})
        self.assertEqual(res_rw.status_code, 200)
        self.assertTrue(res_rw.json()["written"])

        # 5. Read-write key cannot access /admin -> 403
        res_rw_admin = self.client.post("/admin", headers={"Authorization": f"Bearer {rw_key}"})
        self.assertEqual(res_rw_admin.status_code, 403)

        # 6. Admin key can access /admin
        res_admin = self.client.post("/admin", headers={"Authorization": f"Bearer {admin_key}"})
        self.assertEqual(res_admin.status_code, 200)
        self.assertTrue(res_admin.json()["admin"])

    def test_token_bucket_rate_limiter_burst_and_drain(self):
        ro_key = "rate-limited-user-key"
        self.auth_mgr.register_key(ro_key, identity="rate_target", role=Role.READ_ONLY)

        # Capacity is 2.0 tokens for READ_ONLY
        headers = {"X-API-Key": ro_key}
        res1 = self.client.get("/read", headers=headers)
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.get("/read", headers=headers)
        self.assertEqual(res2.status_code, 200)

        # Third request exceeds burst quota -> 429 Too Many Requests
        res3 = self.client.get("/read", headers=headers)
        self.assertEqual(res3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", res3.headers)

    def test_api_key_expiration_and_revocation(self):
        expired_key = "expired-token-key"
        revoked_key = "revoked-token-key"

        past_time = datetime.now(UTC) - timedelta(hours=1)
        self.auth_mgr.register_key(expired_key, identity="old_user", role=Role.READ_ONLY, expires_at=past_time)
        meta_revoked = self.auth_mgr.register_key(revoked_key, identity="bad_user", role=Role.READ_ONLY)
        self.auth_mgr.revoke_key(meta_revoked.fingerprint)

        # Expired key rejected
        res_exp = self.client.get("/read", headers={"Authorization": f"Bearer {expired_key}"})
        self.assertEqual(res_exp.status_code, 401)

        # Revoked key rejected
        res_rev = self.client.get("/read", headers={"Authorization": f"Bearer {revoked_key}"})
        self.assertEqual(res_rev.status_code, 401)

    def test_security_layer_has_zero_storage_imports(self):
        """Security modules must never import SQLite or storage repositories."""
        sec_dir = REPO_ROOT / "src" / "security"
        py_files = [f for f in sec_dir.glob("*.py") if "__pycache__" not in str(f)]

        forbidden = ("sqlite3", "aiosqlite", "src.storage", "storage")
        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for f in forbidden:
                            self.assertFalse(
                                alias.name == f or alias.name.startswith(f + "."),
                                f"{py_file.name} illegally imports {alias.name}",
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for f in forbidden:
                            self.assertFalse(
                                node.module == f or node.module.startswith(f + "."),
                                f"{py_file.name} illegally imports from {node.module}",
                            )
