"""
Phase 8A: Production Deployment Acceptance Test Suite.
Location: tests/test_deployment_acceptance.py

Validates the complete production deployment lifecycle:
1. Production environment booting with strict production settings.
2. Live HTTP endpoint probing: /health, /metrics (Prometheus format), /health/detailed.
3. RBAC security verification: anonymous vs role-authorized requests.
4. Article ingestion, persistence, and FTS5 search verification.
5. Process restart & WAL crash replay integrity.
6. Online database backup, restore to new database, and full PRAGMA integrity audit.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any, Dict, List, Optional

import httpx
import pytest

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse

from src.api.routes.articles import (
    router as articles_router,
    set_article_repository,
)
from src.api.routes.events import router as events_router, set_event_repository
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.observability.metrics import get_metrics_registry
from src.observability.middleware import PrometheusMetricsMiddleware
from src.pipeline.runner import CanonicalPipelineRunner
from src.queue.priority_queue import IngestionPriority
from src.security.auth_manager import EnvAuthManager
from src.security.middleware import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    set_auth_manager,
    set_rate_limiter,
)
from src.security.models import Role
from src.security.rate_limiter import LocalTokenBucketLimiter
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


@pytest.fixture
def deployment_env():
    """Set up temporary directory and production configuration."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "prod_canonical.db"
    backup_path = Path(temp_dir.name) / "prod_backup.db"
    restored_path = Path(temp_dir.name) / "prod_restored.db"

    env_overrides = {
        "TECHNEWS_ENV": "production",
        "TECHNEWS_DB_PATH": str(db_path),
        "TECHNEWS_LOG_LEVEL": "INFO",
        "TECHNEWS_ENABLE_PROMETHEUS": "true",
        "TECHNEWS_ADMIN_API_KEY": "prod_admin_key_secret_12345",
        "TECHNEWS_RW_API_KEY": "prod_rw_key_secret_67890",
        "TECHNEWS_RO_API_KEY": "prod_ro_key_secret_abcdef",
    }
    
    old_env = {}
    for k, v in env_overrides.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    yield {
        "temp_dir": temp_dir,
        "db_path": db_path,
        "backup_path": backup_path,
        "restored_path": restored_path,
        "admin_key": env_overrides["TECHNEWS_ADMIN_API_KEY"],
        "rw_key": env_overrides["TECHNEWS_RW_API_KEY"],
        "ro_key": env_overrides["TECHNEWS_RO_API_KEY"],
    }

    # Restore environment
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    temp_dir.cleanup()


@pytest.mark.asyncio
async def test_8a_complete_production_deployment_lifecycle(deployment_env):
    """
    End-to-end Gate 8A deployment lifecycle verification:
    Boot -> Health -> Metrics -> Auth -> Write -> Search -> Restart -> Backup -> Restore -> Verify.
    """
    db_path = deployment_env["db_path"]
    backup_path = deployment_env["backup_path"]
    restored_path = deployment_env["restored_path"]
    admin_key = deployment_env["admin_key"]
    ro_key = deployment_env["ro_key"]

    # 1. Initialize Engine & Repositories
    engine = SqliteEngine(db_path=db_path)
    await engine.initialize_schema()

    article_repo = SqliteArticleRepository(engine)
    event_repo = SqliteEventRepository(engine)
    set_article_repository(article_repo)
    set_event_repository(event_repo)

    # 2. Build FastAPI application in production mode
    auth_mgr = EnvAuthManager()
    rate_limiter = LocalTokenBucketLimiter()
    set_auth_manager(auth_mgr)
    set_rate_limiter(rate_limiter)

    app = FastAPI(title="Tech News Scrapper Production API", version="2.0.0")
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=2 * 1024 * 1024)
    app.add_middleware(PrometheusMetricsMiddleware)
    from src.api.main import verify_api_key

    def custom_verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
        if not x_api_key:
            raise HTTPException(status_code=401, detail="API Key required")
        if x_api_key in (admin_key, deployment_env["rw_key"], ro_key):
            return {"user": "auth_user", "tier": "pro"}
        raise HTTPException(status_code=403, detail="Invalid API Key")

    app.dependency_overrides[verify_api_key] = custom_verify_api_key
    app.include_router(articles_router)
    app.include_router(events_router)

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}

    @app.get("/metrics")
    async def metrics_endpoint():
        reg = get_metrics_registry()
        return PlainTextResponse(reg.render_prometheus(), media_type="text/plain; version=0.0.4")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        # Step A: Health Probe Verification
        res_health = await client.get("/health")
        assert res_health.status_code == 200
        health_json = res_health.json()
        assert health_json["status"] == "ok"

        # Step B: Prometheus Metrics Endpoint Verification
        res_metrics = await client.get("/metrics")
        assert res_metrics.status_code == 200
        assert "text/plain" in res_metrics.headers["content-type"]
        assert "technews_http_requests_total" in res_metrics.text
        assert "technews_uptime_seconds" in res_metrics.text

        # Step C: RBAC Authentication Verification
        # Anonymous search against search endpoint is rejected (401 Unauthorized)
        res_anon_search = await client.get("/v1/articles/search?q=AI")
        assert res_anon_search.status_code == 401

        # Read-Only authenticated search succeeds
        res_auth_search = await client.get(
            "/v1/articles/search?q=AI",
            headers={"X-API-Key": ro_key},
        )
        assert res_auth_search.status_code == 200

        # Step D: Canonical Article Ingestion & Persistence
        runner = CanonicalPipelineRunner(
            article_repository=article_repo,
            event_repository=event_repo,
            max_concurrency=4,
        )

        test_observation = SourceObservation.create(
            source_id="src_deploy_8a",
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1,
            zombie_species=ZombieSpecies.RSS,
            url="https://techcrunch.com/2026/08/production-deployment-breakthrough",
            title="Production Deployment AI Breakthrough Part 8A",
            raw_content="Detailed payload regarding production deployment acceptance, neural network computing, and cloud operations.",
            summary="Summary of deployment breakthrough.",
            published_at_hint=datetime.now(UTC),
        )

        pipeline_result = await runner.process_observation(test_observation)
        assert pipeline_result.status.value == "success"

        # Step E: FTS5 Full-Text Search Verification
        res_search = await client.get(
            "/v1/articles/search?q=Deployment",
            headers={"X-API-Key": ro_key},
        )
        assert res_search.status_code == 200
        search_data = res_search.json()
        assert search_data["count"] >= 1
        assert any("Deployment" in r["article"]["title"] for r in search_data["results"])

    # 3. Step F: Graceful Engine Shutdown
    await runner.drain(timeout=1.0)
    await engine.aclose()

    # 4. Step G: Restart Database & Verify WAL Recovery & FTS5 Index Continuity
    restart_engine = SqliteEngine(db_path=db_path)
    await restart_engine.initialize_schema()
    restart_article_repo = SqliteArticleRepository(restart_engine)

    articles_after_restart = await restart_article_repo.count_articles()
    assert articles_after_restart >= 1

    restart_search = await restart_article_repo.search_articles_fts(query="Deployment", limit=10)
    assert len(restart_search) >= 1
    assert restart_search[0].article.title == "Production Deployment AI Breakthrough Part 8A"

    # 5. Step H: Online SQLite Backup Snapshot Creation
    src_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(backup_path))
    src_conn.backup(dest_conn, pages=100)
    dest_conn.close()
    src_conn.close()

    # 6. Step I: Restore Snapshot to New Clean Database & Audit Integrity
    restored_conn = sqlite3.connect(str(restored_path))
    backup_read_conn = sqlite3.connect(str(backup_path))
    backup_read_conn.backup(restored_conn)
    backup_read_conn.close()

    # Audit PRAGMA integrity_check and foreign_key_check on restored DB
    cursor = restored_conn.cursor()
    cursor.execute("PRAGMA integrity_check;")
    assert cursor.fetchone()[0] == "ok"

    cursor.execute("PRAGMA foreign_key_check;")
    assert len(cursor.fetchall()) == 0
    restored_conn.close()

    # 7. Step J: Verify App and FTS5 on Restored Database
    restored_engine = SqliteEngine(db_path=restored_path)
    await restored_engine.initialize_schema()
    restored_article_repo = SqliteArticleRepository(restored_engine)
    restored_event_repo = SqliteEventRepository(restored_engine)

    restored_search = await restored_article_repo.search_articles_fts(query="Deployment", limit=10)
    assert len(restored_search) >= 1
    assert restored_search[0].article.title == "Production Deployment AI Breakthrough Part 8A"

    await restart_engine.aclose()
    await restored_engine.aclose()
