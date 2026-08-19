"""
Tests for Subphase 5F-C: Auxiliary Consumer Migration (5F-C1 to 5F-C4).
Location: tests/test_api_auxiliary_migration.py

Validates:
1. 5F-C1: /v1/search backed by ArticleRepositoryProtocol and SqliteArticleRepository.
2. 5F-C1: /v1/sentiment/analyze, /v1/sentiment/trends, /v1/sentiment/article/{id} backed by ArticleRepositoryProtocol.
3. 5F-C1: Dev app (src.api.main) lifespan and health checks.
4. 5F-C2: UserPreferencesManager and DataPrivacyManager on canonical SQLite storage.
5. 5F-C3: Operational diagnostics, health endpoints, and Celery retention tasks.
6. 5F-C4: Discovery wrapper store isolation.
7. AST static inspection asserting zero imports of legacy Database in all migrated modules.
"""

from __future__ import annotations

import ast
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

from src.api.app import app as prod_app
from src.api.main import app as dev_app, verify_api_key
from src.api.routes.articles import get_article_repository, set_article_repository
from src.api.routes.events import set_event_repository
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle
from src.storage.protocols import ArticleRepositoryProtocol
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


class SpyArticleRepository(ArticleRepositoryProtocol):
    """In-memory spy repository implementing ArticleRepositoryProtocol for tests."""

    def __init__(self) -> None:
        self.articles: dict[str, NormalizedArticle] = {}

    async def save_article(self, article: NormalizedArticle) -> None:
        self.articles[article.id] = article

    async def save_articles(self, articles: List[NormalizedArticle]) -> int:
        for a in articles:
            self.articles[a.id] = a
        return len(articles)

    async def get_article(self, article_id: str) -> Optional[NormalizedArticle]:
        return self.articles.get(article_id)

    async def get_article_by_canonical_url(self, canonical_url: str) -> Optional[NormalizedArticle]:
        for a in self.articles.values():
            if a.canonical_url == canonical_url:
                return a
        return None

    async def get_recent_articles(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
    ) -> List[NormalizedArticle]:
        items = list(self.articles.values())
        if source_id:
            items = [a for a in items if a.source_id == source_id]
        return items[offset : offset + limit]

    async def count_articles(self) -> int:
        return len(self.articles)

    async def search_articles(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[NormalizedArticle]:
        q = query.lower()
        matches = [
            a for a in self.articles.values()
            if q in a.title.lower() or q in (a.clean_text or "").lower() or q in (a.summary or "").lower()
        ]
        return matches[offset : offset + limit]

    async def delete_article(self, article_id: str) -> bool:
        if article_id in self.articles:
            del self.articles[article_id]
            return True
        return False

    async def delete_articles_older_than(self, cutoff: datetime) -> int:
        to_del = [aid for aid, a in self.articles.items() if a.discovered_at < cutoff]
        for aid in to_del:
            del self.articles[aid]
        return len(to_del)


def _make_article(article_id: str, title: str, summary: str = "", text: str = "") -> NormalizedArticle:
    now = datetime.now(UTC)
    return NormalizedArticle(
        id=article_id,
        canonical_url=f"https://example.com/{article_id}",
        original_url=f"https://example.com/{article_id}",
        title=title,
        clean_text=text or f"Full content text for {title}",
        summary=summary or f"Summary for {title}",
        source_id="techcrunch",
        source_name="TechCrunch",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        discovered_at=now,
        published_at=now,
        language="en",
        image_url=None,
        authors=("Jane Doe",),
        tags=("tech", "ai"),
        metadata={},
    )


# =============================================================================
# 1. 5F-C1: SEARCH ENDPOINT MIGRATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_search_endpoint_with_article_repository() -> None:
    """Verify /v1/search retrieves matching articles from ArticleRepositoryProtocol."""
    spy_repo = SpyArticleRepository()
    art1 = _make_article("art_quantum_1", "Quantum Computing Breakthrough", summary="Qubit fidelity record")
    art2 = _make_article("art_ai_1", "Autonomous AI Agents in Production", summary="Multi-agent orchestration")
    await spy_repo.save_articles([art1, art2])

    prod_app.dependency_overrides[get_article_repository] = lambda: spy_repo
    prod_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro", "user_id": "test"}

    try:
        with TestClient(prod_app) as client:
            res = client.get("/v1/search?q=Quantum")
            assert res.status_code == 200
            data = res.json()
            assert data["page"] == 1
            assert len(data["articles"]) == 1
            assert data["articles"][0]["id"] == "art_quantum_1"
            assert data["articles"][0]["title"] == "Quantum Computing Breakthrough"

            # Search with no match
            res_none = client.get("/v1/search?q=Biotech")
            assert res_none.status_code == 200
            assert len(res_none.json()["articles"]) == 0
    finally:
        prod_app.dependency_overrides.clear()


# =============================================================================
# 2. 5F-C1: SENTIMENT ENDPOINT MIGRATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_sentiment_endpoints_with_article_repository() -> None:
    """Verify sentiment analysis and article sentiment lookup via ArticleRepositoryProtocol."""
    spy_repo = SpyArticleRepository()
    art = _make_article(
        "art_positive",
        "Record Growth in Clean Fusion Energy",
        text="Astonishing progress and breakthrough achievements reported today.",
    )
    await spy_repo.save_article(art)

    prod_app.dependency_overrides[get_article_repository] = lambda: spy_repo
    prod_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro", "user_id": "test"}

    try:
        with TestClient(prod_app) as client:
            # 1. Direct text analysis
            res_text = client.get("/v1/sentiment/analyze?text=Incredible%20breakthrough%20innovation%20achieved!")
            assert res_text.status_code == 200
            data_text = res_text.json()
            assert "score" in data_text
            assert "label" in data_text

            # 2. Trends
            res_trends = client.get("/v1/sentiment/trends?period=24h")
            assert res_trends.status_code == 200
            assert isinstance(res_trends.json(), list)

            # 3. Article sentiment resolution via repository
            res_art = client.get("/v1/sentiment/article/art_positive")
            assert res_art.status_code == 200
            data_art = res_art.json()
            assert "score" in data_art
            assert "label" in data_art

            # 4. Non-existent article
            res_404 = client.get("/v1/sentiment/article/non_existent_id")
            assert res_404.status_code == 404
    finally:
        prod_app.dependency_overrides.clear()


# =============================================================================
# 3. 5F-C1: DEV MAIN APP LIFESPAN & HEALTH TEST
# =============================================================================

@pytest.mark.asyncio
async def test_dev_app_lifespan_and_health(tmp_path: Path) -> None:
    """Verify src.api.main lifespan initializes both repositories and /health endpoint."""
    test_db = tmp_path / "dev_main_canonical.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    try:
        with TestClient(dev_app) as client:
            res_health = client.get("/health")
            assert res_health.status_code == 200
            data = res_health.json()
            assert data["status"] == "healthy"
            assert data["database"] == "connected"
            assert data["articles_count"] == 0
    finally:
        os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


# =============================================================================
# 4. 5F-C2: USER PREFERENCES & DATA PRIVACY CANONICAL COMPATIBILITY
# =============================================================================

def test_user_preferences_manager_canonical_roundtrip() -> None:
    """Verify UserPreferencesManager operates on canonical database schema without legacy Database."""
    from src.user.preferences import UserPreferencesManager, UserPreferences, TopicSubscription

    manager = UserPreferencesManager()
    user_id = f"user_c2_test_{int(datetime.now(UTC).timestamp() * 1000)}"
    prefs = manager.get_preferences(user_id)
    assert prefs.user_id == user_id
    assert prefs.display_name == "User"

    prefs.display_name = "Alice Canonical"
    prefs.topics = [TopicSubscription(topic="Quantum", weight=0.9)]
    saved = manager.save_preferences(prefs)
    assert saved is True

    # Re-fetch from cache and clean instance
    fresh_manager = UserPreferencesManager()
    fetched = fresh_manager.get_preferences(user_id)
    assert fetched.display_name == "Alice Canonical"
    assert len(fetched.topics) == 1
    assert fetched.topics[0].topic == "Quantum"


def test_data_privacy_manager_canonical_operations() -> None:
    """Verify DataPrivacyManager processes deletion, export, and retention without legacy Database."""
    from src.compliance.data_privacy_manager import DataPrivacyManager

    privacy_manager = DataPrivacyManager()
    user_id = "user_privacy_test"

    # Export
    export = privacy_manager.export_user_data(user_id)
    assert export.user_id == user_id
    assert "export_date" in export.data

    # Deletion
    del_report = privacy_manager.process_deletion_request(user_id)
    assert del_report.success is True

    # Retention
    ret_report = privacy_manager.apply_retention_policy()
    assert ret_report is not None


# =============================================================================
# 5. 5F-C3: OPERATIONAL DIAGNOSTICS & RETENTION TASKS
# =============================================================================

@pytest.mark.asyncio
async def test_operational_diagnostics_and_health_checks() -> None:
    """Verify health checker and diagnostic toolkit succeed against canonical schema."""
    from src.monitoring.health_check_endpoints import get_health_checker
    from src.operations.diagnostic_toolkit import DiagnosticToolkit

    checker = get_health_checker()
    db_health = await checker.check_database()
    assert db_health.status == "healthy"
    assert db_health.details["type"] == "canonical_sqlite"

    toolkit = DiagnosticToolkit()
    diag_result = toolkit.check_database()
    assert diag_result.status == "pass"
    assert diag_result.details["type"] == "canonical_sqlite"


def test_celery_cleanup_old_articles_task() -> None:
    """Verify cleanup_old_articles Celery task runs against canonical storage."""
    from src.queue.tasks import cleanup_old_articles

    res = cleanup_old_articles(days_old=30)
    assert res["status"] == "success"
    assert "deleted_count" in res


# =============================================================================
# 6. 5F-C4: DISCOVERY AGENT DEFAULT STORE ISOLATION
# =============================================================================

def test_discovery_agent_default_store() -> None:
    """Verify DiscoveryAgent instantiates cleanly without legacy Database."""
    from src.discovery import DiscoveryAgent, WebDiscoveryAgent

    agent1 = WebDiscoveryAgent()
    assert hasattr(agent1.db, "add_discovered_source")

    agent2 = DiscoveryAgent()
    assert hasattr(agent2.db, "add_discovered_source")


# =============================================================================
# 7. AST ZERO LEGACY STORAGE IMPORTS IN ALL MIGRATED MODULES
# =============================================================================

def test_ast_all_migrated_modules_zero_legacy_imports() -> None:
    """Verify all 5F-C migrated modules have 0 imports of legacy Database or db_storage."""
    migrated_files = [
        Path("src/api/routes/search.py"),
        Path("src/api/routes/sentiment.py"),
        Path("src/api/main.py"),
        Path("src/api/app.py"),
        Path("src/user/preferences.py"),
        Path("src/compliance/data_privacy_manager.py"),
        Path("src/monitoring/health_check_endpoints.py"),
        Path("src/operations/diagnostic_toolkit.py"),
        Path("src/queue/tasks.py"),
        Path("src/discovery/__init__.py"),
    ]

    forbidden_patterns = [
        "src.database",
        "database.Database",
        "src.db_storage",
    ]

    for file_path in migrated_files:
        assert file_path.exists(), f"{file_path} must exist"
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_patterns:
                        assert forbidden not in alias.name, (
                            f"Forbidden import '{alias.name}' in {file_path} at line {node.lineno}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_patterns:
                        assert forbidden not in node.module, (
                            f"Forbidden from-import '{node.module}' in {file_path} at line {node.lineno}"
                        )
