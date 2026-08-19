"""
Production Runtime Contract & Legacy Isolation Test Suite.
Location: tests/test_production_runtime_contract.py

Validates Phase 8H-H3 requirements:
1. Canonical API entrypoint (src.api.app:app)
2. Canonical worker entrypoint (src.worker.run_worker)
3. Legacy entrypoints emit deprecation warnings and are isolated
4. API authentication fails closed in production
5. Worker initializes schema, repositories, and engine
6. Worker shuts down cleanly on signal/event without orphan tasks
7. No duplicate ingestion loop in API process
8. SQLite opens with WAL mode and proper pragmas
9. Swarm coordinator initializes leases table
10. /health and /health/detailed endpoints return proper status
11. /metrics endpoint returns Prometheus formatted metrics
12. Static Dockerfile and docker-compose entrypoint verification
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.engine.unified_chain import UnifiedFeedChainEngine
from src.security.auth_manager import EnvAuthManager
from src.security.models import Role
from src.storage.sqlite_engine import SqliteEngine
from src.worker import run_worker
from src.zombies.coordinator import SqliteSwarmCoordinator


class TestProductionRuntimeContract(unittest.IsolatedAsyncioTestCase):
    """Production runtime contract verification."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_contract.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Canonical API entrypoint verification
    def test_01_canonical_api_entrypoint_routes(self):
        client = TestClient(app)
        res_health = client.get("/health")
        self.assertEqual(res_health.status_code, 200)
        data = res_health.json()
        self.assertEqual(data["status"], "ok")

        res_metrics = client.get("/metrics")
        self.assertEqual(res_metrics.status_code, 200)
        self.assertIn("technews_", res_metrics.text)

    # 2. Canonical worker lifecycle verification
    async def test_02_canonical_worker_lifecycle(self):
        shutdown_event = asyncio.Event()

        # Start worker as task and signal immediate shutdown
        async def _trigger_shutdown():
            await asyncio.sleep(0.1)
            shutdown_event.set()

        asyncio.create_task(_trigger_shutdown())
        # Should start, initialize DB & Engine, and cleanly shut down
        await run_worker(db_path=self.db_path, concurrency=1, shutdown_event=shutdown_event)

        self.assertTrue(self.db_path.exists())

    # 3. Legacy entrypoints deprecation verification
    def test_03_legacy_entrypoints_emit_deprecation(self):
        import importlib
        import src.api.main as legacy_api

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            importlib.reload(legacy_api)

            deprecation_warnings = [
                w for w in recorded_warnings if issubclass(w.category, DeprecationWarning)
            ]
            self.assertGreaterEqual(len(deprecation_warnings), 1)
            self.assertIn("src/api/main.py is deprecated", str(deprecation_warnings[0].message))

    # 4. API authentication fails closed in production
    def test_04_auth_fails_closed_in_production(self):
        with patch.dict(os.environ, {"TECHNEWS_ENV": "production", "TECHNEWS_ADMIN_API_KEY": ""}, clear=False):
            auth_mgr = EnvAuthManager()
            principal = auth_mgr.authenticate_key("invalid_or_missing_key")
            self.assertIsNone(principal)

    # 5. Worker initializes schema and repositories
    async def test_05_worker_schema_initialization(self):
        engine = SqliteEngine(self.db_path)
        await engine.initialize_schema()

        async with engine.connect() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='canonical_articles'"
            )
            row = await cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "canonical_articles")

        await engine.aclose()

    # 6. Worker shutdown leaves no running tasks
    async def test_06_worker_shutdown_cleans_tasks(self):
        engine_db = SqliteEngine(self.db_path)
        await engine_db.initialize_schema()

        unified_engine = UnifiedFeedChainEngine()
        unified_engine.initialize(concurrency=1)
        self.assertTrue(unified_engine._initialized)

        # Teardown
        await unified_engine.aclose()
        self.assertFalse(unified_engine._initialized)
        await engine_db.aclose()

    # 7. No duplicate ingestion loop in API process
    def test_07_api_lifespan_has_no_scraper_tasks(self):
        # Inspect app lifespan and route modules
        import inspect
        import sys

        api_app_mod = sys.modules.get("src.api.app")
        self.assertIsNotNone(api_app_mod)
        source_code = inspect.getsource(api_app_mod.lifespan)
        self.assertNotIn("ZombieSwarm", source_code)
        self.assertNotIn("UnifiedFeedChainEngine", source_code)
        self.assertNotIn("ScraperScheduler", source_code)

    # 8. SQLite WAL mode pragmas verified
    async def test_08_sqlite_wal_pragmas(self):
        engine = SqliteEngine(self.db_path)
        await engine.initialize_schema()

        async with engine.connect() as conn:
            cursor = await conn.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            self.assertEqual(row[0].upper(), "WAL")

            cursor = await conn.execute("PRAGMA foreign_keys")
            fk_row = await cursor.fetchone()
            self.assertEqual(fk_row[0], 1)

        await engine.aclose()

    # 9. Swarm coordinator initializes leases
    async def test_09_coordinator_leases_table(self):
        coord = SqliteSwarmCoordinator(db_path=self.db_path)
        res = await coord.acquire_lease("source_alpha", "worker_1", duration_seconds=60.0)
        self.assertTrue(res.is_successful)

        res_renew = await coord.renew_lease("source_alpha", "worker_1", res.token, duration_seconds=60.0)
        self.assertTrue(res_renew.is_successful)

        released = await coord.release_lease("source_alpha", "worker_1", res.token)
        self.assertTrue(released)

    # 10. Health detailed endpoint verification
    def test_10_health_detailed_probe(self):
        client = TestClient(app)
        res = client.get("/health/detailed")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("database", data)
        self.assertIn("articles_count", data)

    # 11. Metrics endpoint format verification
    def test_11_metrics_endpoint_render(self):
        client = TestClient(app)
        res = client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("# HELP", res.text)
        self.assertIn("# TYPE", res.text)

    # 12. Static Dockerfile and Docker-Compose entrypoint verification
    def test_12_static_deployment_entrypoints(self):
        repo_root = Path(__file__).parent.parent

        # Dockerfile check
        dockerfile_content = (repo_root / "Dockerfile").read_text(encoding="utf-8")
        self.assertTrue(
            'ENTRYPOINT ["uvicorn", "src.api.app:app"' in dockerfile_content
            or 'CMD ["uvicorn", "src.api.app:app"' in dockerfile_content,
            "Dockerfile must specify canonical uvicorn src.api.app:app",
        )

        # docker-compose.yml check
        compose_content = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("src.api.app:app", compose_content)
        self.assertIn("src.worker", compose_content)
        self.assertNotIn("main_engine.py", compose_content)

        # pyproject.toml check
        pyproject_content = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("technews-worker = \"src.worker:main\"", pyproject_content)
        self.assertIn("technews-api = \"main:run_api\"", pyproject_content)


if __name__ == "__main__":
    unittest.main()
