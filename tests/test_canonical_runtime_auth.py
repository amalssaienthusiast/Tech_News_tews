"""
Architecture & Security Tests for Canonical Production Runtime and Auth Hardening.
Location: tests/test_canonical_runtime_auth.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import os
from pathlib import Path
import tempfile
import unittest

import httpx
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.app import app, verify_api_key
from src.engine.unified_chain import UnifiedFeedChainEngine
from src.security.auth_manager import EnvAuthManager
from src.security.middleware import get_auth_manager, set_auth_manager
from src.security.models import Role
from src.security.policy import verify_engine_api_key
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


class TestCanonicalRuntimeAndAuth(unittest.TestCase):
    """Test suite verifying canonical runtime initialization, auth fail-closed behavior, and RBAC."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_canonical.db"
        self.old_env = dict(os.environ)

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.clear()
        os.environ.update(self.old_env)
        set_auth_manager(None)

    def test_auth_fail_closed_in_production_policy(self):
        """Verify that verify_engine_api_key fails closed when in production and key is unset."""
        os.environ["TECHNEWS_ENV"] = "production"
        os.environ.pop("ENGINE_API_KEY", None)

        # In production with missing ENGINE_API_KEY, must fail closed (return False)
        self.assertFalse(verify_engine_api_key(None))
        self.assertFalse(verify_engine_api_key("some_random_key"))

        # In dev mode, missing ENGINE_API_KEY allows local fallback
        os.environ["TECHNEWS_ENV"] = "development"
        self.assertTrue(verify_engine_api_key(None))

    def test_env_auth_manager_rbac_key_loading(self):
        """Verify EnvAuthManager automatically registers ADMIN, RW, and RO keys from environment."""
        os.environ["TECHNEWS_ADMIN_API_KEY"] = "admin_secret_token_12345"
        os.environ["TECHNEWS_RW_API_KEY"] = "rw_secret_token_67890"
        os.environ["TECHNEWS_RO_API_KEY"] = "ro_secret_token_abcde"

        auth_mgr = EnvAuthManager()

        admin_p = auth_mgr.authenticate_key("admin_secret_token_12345")
        self.assertIsNotNone(admin_p)
        self.assertEqual(admin_p.role, Role.ADMIN)
        self.assertEqual(admin_p.identity, "system_admin")

        rw_p = auth_mgr.authenticate_key("rw_secret_token_67890")
        self.assertIsNotNone(rw_p)
        self.assertEqual(rw_p.role, Role.READ_WRITE)
        self.assertEqual(rw_p.identity, "ingestion_service")

        ro_p = auth_mgr.authenticate_key("ro_secret_token_abcde")
        self.assertIsNotNone(ro_p)
        self.assertEqual(ro_p.role, Role.READ_ONLY)
        self.assertEqual(ro_p.identity, "reader_client")

        # Invalid key returns None
        self.assertIsNone(auth_mgr.authenticate_key("wrong_token"))

    def test_fastapi_app_auth_integration_fail_closed(self):
        """Verify FastAPI endpoints enforce auth and fail-closed when API_ALLOW_ANONYMOUS=false."""
        os.environ["API_ALLOW_ANONYMOUS"] = "false"
        os.environ["TECHNEWS_ADMIN_API_KEY"] = "prod_admin_key_999"
        os.environ["TECHNEWS_RO_API_KEY"] = "prod_ro_key_111"

        # Configure fresh auth manager
        set_auth_manager(EnvAuthManager())

        with TestClient(app) as client:
            # 1. Public endpoints must work without authentication
            health_res = client.get("/health")
            self.assertEqual(health_res.status_code, 200)
            self.assertEqual(health_res.json()["status"], "ok")

            metrics_res = client.get("/metrics")
            self.assertEqual(metrics_res.status_code, 200)
            self.assertIn("# HELP", metrics_res.text)

            # 2. Protected endpoints without key must return 401 Unauthorized
            root_res = client.get("/")
            self.assertEqual(root_res.status_code, 401)

            # 3. Protected endpoint with invalid key must return 401 Unauthorized
            invalid_res = client.get("/", headers={"X-API-Key": "invalid_key_xyz"})
            self.assertEqual(invalid_res.status_code, 401)

            # 4. Protected endpoint with valid RO key must succeed
            valid_ro_res = client.get("/", headers={"X-API-Key": "prod_ro_key_111"})
            self.assertEqual(valid_ro_res.status_code, 200)
            self.assertEqual(valid_ro_res.json()["tier"], "free")

            # 5. Protected endpoint with valid ADMIN key must succeed
            valid_admin_res = client.get("/", headers={"X-API-Key": "prod_admin_key_999"})
            self.assertEqual(valid_admin_res.status_code, 200)
            self.assertEqual(valid_admin_res.json()["tier"], "pro")

    def test_unified_feed_chain_engine_lifecycle(self):
        """Verify UnifiedFeedChainEngine initializes canonical pipeline and registry."""
        engine = SqliteEngine(self.db_path)
        article_repo = SqliteArticleRepository(engine)
        event_repo = SqliteEventRepository(engine)

        unified = UnifiedFeedChainEngine(
            event_repository=event_repo,
            article_repository=article_repo,
        )
        unified.initialize(concurrency=2)
        self.assertTrue(unified._initialized)
        self.assertIsNotNone(unified.canonical_runner)
        self.assertIsNotNone(unified.swarm)
        self.assertIsNotNone(unified.bus)
        unified.stop()

    def test_api_key_manager_lifecycle_and_fresh_db(self):
        """P1-2 Regression: Verify APIKeyManager self-initializes schema, creates valid keys, and validates."""
        import sqlite3
        from src.api.auth import APIKeyManager

        fresh_db = Path(self.temp_dir.name) / "fresh_auth.db"
        self.assertFalse(fresh_db.exists())

        # 1. Instantiate on fresh DB -> schema must be created automatically
        mgr = APIKeyManager(db_path=fresh_db)
        self.assertTrue(fresh_db.exists())

        # Verify table exists in SQLite master
        with sqlite3.connect(str(fresh_db)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'")
            self.assertIsNotNone(cur.fetchone())

        # 2. Prove create_key() returns a valid key
        plaintext = mgr.create_key(user_id="user_123", tier="pro", name="test-key")
        self.assertTrue(plaintext.startswith("tns_"))
        self.assertGreater(len(plaintext), 20)

        # 3. Prove that key validation works
        validated = mgr.validate_key(plaintext)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["user_id"], "user_123")
        self.assertEqual(validated["tier"], "pro")
        self.assertIn("key_id", validated)

        # 4. Prove invalid key validation returns None
        self.assertIsNone(mgr.validate_key("tns_invalid_token_999"))
        self.assertIsNone(mgr.validate_key(""))

        # 5. Prove schema errors are not silently swallowed
        invalid_target = fresh_db / "cannot_be_a_dir" / "bad.db"
        with self.assertRaises(Exception):
            APIKeyManager(db_path=invalid_target)


if __name__ == "__main__":
    unittest.main()
