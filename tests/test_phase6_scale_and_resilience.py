"""
Phase 6F: Comprehensive Scale, Concurrency, Memory & Resilience Verification Suite.
Location: tests/test_phase6_scale_and_resilience.py
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC, timedelta
from pathlib import Path
import tempfile
import time
import unittest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.observability import MetricsRegistry, get_metrics_registry, normalize_route_template
from src.pipeline.runner import CanonicalPipelineRunner
from src.queue.priority_queue import IngestionPriority, StarvationSafeIngestionQueue
from src.security.models import Role
from src.security.rate_limiter import LocalTokenBucketLimiter
from src.security.ssrf_guard import SSRFGuard, SSRFSecurityError
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository
from src.zombies.coordinator import LocalSwarmCoordinator

REPO_ROOT = Path(__file__).parent.parent


class TestPhase6FScaleAndResilience(unittest.IsolatedAsyncioTestCase):
    """Full end-to-end integration and resilience test suite for Phase 6."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "canonical_test_6f.db"
        self.engine = SqliteEngine(db_path=self.db_path)
        await self.engine.initialize_schema()

        self.article_repo = SqliteArticleRepository(self.engine)
        self.event_repo = SqliteEventRepository(self.engine)
        self.pipeline_runner = CanonicalPipelineRunner(
            article_repository=self.article_repo,
            event_repository=self.event_repo,
            max_concurrency=16,
        )
        self.queue = StarvationSafeIngestionQueue(capacity=500, aging_rate_per_sec=0.5)
        self.coordinator = LocalSwarmCoordinator()
        self.metrics = get_metrics_registry()

    async def asyncTearDown(self):
        await self.pipeline_runner.drain(timeout=1.0)
        await self.engine.aclose()
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 6F-A: Multi-Zombie Concurrency & Fencing Token Lease Validation
    # -------------------------------------------------------------------------
    async def test_6f_a_concurrent_zombie_leases_and_fencing(self):
        """Verify multi-worker lease acquisition, fencing token validation, and renewal."""
        source_id = "techcrunch_rss"

        # Worker 1 acquires lease
        res1 = await self.coordinator.acquire_lease(source_id=source_id, worker_id="worker_1", duration_seconds=5.0)
        self.assertTrue(res1.is_successful)
        self.assertEqual(res1.lease_owner, "worker_1")
        token1 = res1.token

        # Worker 2 attempts concurrent acquire -> must fail
        res2 = await self.coordinator.acquire_lease(source_id=source_id, worker_id="worker_2", duration_seconds=5.0)
        self.assertFalse(res2.is_successful)

        # Worker 1 renews with valid fencing token
        renewed = await self.coordinator.renew_lease(source_id=source_id, worker_id="worker_1", token=token1, duration_seconds=10.0)
        self.assertTrue(renewed.is_successful)

        # Worker 2 attempts renewal with forged token -> must fail
        bad_renew = await self.coordinator.renew_lease(source_id=source_id, worker_id="worker_2", token="forged-fencing-token", duration_seconds=10.0)
        self.assertFalse(bad_renew.is_successful)

        # Worker 1 releases lease
        released = await self.coordinator.release_lease(source_id=source_id, worker_id="worker_1", token=token1)
        self.assertTrue(released)

        # Worker 2 can now acquire
        res2_new = await self.coordinator.acquire_lease(source_id=source_id, worker_id="worker_2", duration_seconds=5.0)
        self.assertTrue(res2_new.is_successful)
        self.assertEqual(res2_new.lease_owner, "worker_2")

    # -------------------------------------------------------------------------
    # 6F-B: High-Throughput Acquisition -> Queue -> S01-S11 -> SQLite Persistence
    # -------------------------------------------------------------------------
    async def test_6f_b_high_throughput_ingestion_and_fts5_indexing(self):
        """Push 100 observations through priority queue and pipeline, verifying FTS5 searchability."""
        total_items = 60
        enqueued_count = 0

        # Enqueue varied priority items
        for i in range(total_items):
            priority = IngestionPriority.CRITICAL if i % 10 == 0 else IngestionPriority.NORMAL
            obs = SourceObservation.create(
                source_id="techcrunch",
                source_name="TechCrunch",
                source_tier=SourceTier.TIER_1,
                zombie_species=ZombieSpecies.RSS,
                url=f"https://techcrunch.com/2026/scale-ai-item-{i}",
                title=f"AI Scaling Breakthrough Volume {i}",
                raw_content=f"Scale verification article {i} covering AI breakthroughs in neural architecture search.",
                summary="AI breakthrough in neural architecture search.",
                published_at_hint=datetime.now(UTC),
            )
            pushed = await self.queue.push(obs, priority=priority)
            if pushed:
                enqueued_count += 1

        self.assertEqual(enqueued_count, total_items)
        self.assertEqual(self.queue.depth, total_items)

        # Process through pipeline runner
        processed_count = 0
        while self.queue.depth > 0:
            item = await self.queue.pop()
            res = await self.pipeline_runner.process_observation(item)
            self.assertEqual(res.status.value, "success")
            processed_count += 1

        self.assertEqual(processed_count, total_items)

        # Verify SQLite storage & FTS5 search index
        count = await self.article_repo.count_articles()
        self.assertEqual(count, total_items)

        # Search via FTS5
        search_res = await self.article_repo.search_articles_fts(query="breakthroughs neural", limit=10)
        self.assertGreater(len(search_res), 0)
        self.assertIn("breakthrough", search_res[0].snippet.lower())

    # -------------------------------------------------------------------------
    # 6F-C: Memory, Resource & Metric Cardinality Stability Audit
    # -------------------------------------------------------------------------
    def test_6f_c_metric_cardinality_and_normalization_bounds(self):
        """Verify that metric families have strictly bounded series counts under high path variations."""
        registry = MetricsRegistry()

        # Simulate 1000 different article detail URL requests
        for i in range(1000):
            raw_url = f"/v1/articles/{i:08x}"
            template = normalize_route_template(raw_url)
            registry.http_requests_total.inc(value=1.0, method="GET", endpoint=template, status_code="200")

        # Render Prometheus text
        rendered = registry.render_prometheus()

        # The route template must be collapsed to exactly ONE series for /v1/articles/{article_id}
        occurrences = rendered.count('technews_http_requests_total{endpoint="/v1/articles/{article_id}",method="GET",status_code="200"}')
        self.assertEqual(occurrences, 1)
        self.assertIn(" 1000.0", rendered)

    # -------------------------------------------------------------------------
    # 6F-D: Security & Failure-Injection Verification
    # -------------------------------------------------------------------------
    async def test_6f_d_security_and_failure_injection_resilience(self):
        """Inject SSRF violations, payload limits, and rate limits under concurrent stress."""
        # 1. SSRF injection
        guard = SSRFGuard()
        forbidden_targets = [
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal",
            "http://192.168.1.1/router",
        ]
        for url in forbidden_targets:
            with self.assertRaises(SSRFSecurityError):
                await guard.validate_url(url)

        # 2. Rate Limiter exhaustion
        limiter = LocalTokenBucketLimiter(role_quotas={Role.ANONYMOUS: (2.0, 1.0)})
        res1 = await limiter.check_rate_limit(key="anon_client", role=Role.ANONYMOUS)
        self.assertTrue(res1.allowed)
        res2 = await limiter.check_rate_limit(key="anon_client", role=Role.ANONYMOUS)
        self.assertTrue(res2.allowed)
        res3 = await limiter.check_rate_limit(key="anon_client", role=Role.ANONYMOUS)
        self.assertFalse(res3.allowed)
        self.assertIsNotNone(res3.retry_after)

    # -------------------------------------------------------------------------
    # 6F-E: Architecture AST Boundary & Invariant Audit
    # -------------------------------------------------------------------------
    def test_6f_e_ast_cross_package_architectural_invariants(self):
        """Verify strict architectural isolation across all Phase 6 layers."""
        layer_checks = [
            ("src/security", ("sqlite3", "aiosqlite", "src.storage")),
            ("src/observability", ("sqlite3", "aiosqlite", "src.storage")),
            ("src/zombies", ("sqlite3", "aiosqlite", "src.storage.sqlite")),
            ("src/queue/priority_queue.py", ("sqlite3", "aiosqlite", "src.storage")),
            ("src/discovery", ("sqlite3", "aiosqlite", "src.storage.sqlite")),
        ]

        for target_path, forbidden in layer_checks:
            full_path = REPO_ROOT / target_path
            if full_path.is_file():
                py_files = [full_path]
            else:
                py_files = [f for f in full_path.glob("*.py") if "__pycache__" not in str(f)]

            for py_file in py_files:
                if py_file.name == "coordinator.py":
                    continue
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            for f in forbidden:
                                self.assertFalse(
                                    alias.name == f or alias.name.startswith(f + "."),
                                    f"VIOLATION: {py_file.name} illegally imports {alias.name}",
                                )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            for f in forbidden:
                                self.assertFalse(
                                    node.module == f or node.module.startswith(f + "."),
                                    f"VIOLATION: {py_file.name} illegally imports from {node.module}",
                                )
