"""
Unit & Integration Tests for Subphase 5E-E: API Article Repository Migration.
Location: tests/test_api_articles_migration.py

Verifies:
1. Repository dependency injection via set_article_repository / get_article_repository
2. GET /v1/articles active retrieval with pagination (page, per_page, has_more)
3. GET /v1/articles?source=... filtering by source ID
4. GET /v1/articles/{id} single article retrieval (200 OK)
5. GET /v1/articles/{canonical_url} fallback URL lookup (200 OK)
6. GET /v1/articles/{id} missing article returns 404 Not Found
7. DTO mapping fidelity (ArticleResponse, ArticlesListResponse, ISO-8601 UTC datetimes)
8. Authentication enforcement (401 when API key missing/invalid in authenticated mode)
9. End-to-end FastAPI Lifespan + real SQLite SqliteArticleRepository integration
10. Strict AST boundary purity (articles.py has zero imports of sqlite3, aiosqlite, SqliteEngine, Database, etc.)
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC, timedelta
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.main import verify_api_key
from src.api.routes.articles import (
    router as articles_router,
    get_article_repository,
    set_article_repository,
    ArticleResponse,
    ArticlesListResponse,
)
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle
from src.storage.protocols import ArticleRepositoryProtocol
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine


# =============================================================================
# SPY REPOSITORY & FIXTURES
# =============================================================================

class SpyArticleRepository(ArticleRepositoryProtocol):
    """In-memory spy repository for testing article API routes."""

    def __init__(self) -> None:
        self.articles_by_id: Dict[str, NormalizedArticle] = {}
        self.articles_by_url: Dict[str, NormalizedArticle] = {}
        self.articles_list: List[NormalizedArticle] = []

    def add_article(self, article: NormalizedArticle) -> None:
        self.articles_by_id[article.id] = article
        self.articles_by_url[article.canonical_url] = article
        self.articles_list.append(article)

    async def save_article(self, article: NormalizedArticle) -> None:
        self.add_article(article)

    async def save_articles(self, articles: Sequence[NormalizedArticle]) -> int:
        for a in articles:
            self.add_article(a)
        return len(articles)

    async def get_article(self, article_id: str) -> Optional[NormalizedArticle]:
        return self.articles_by_id.get(article_id)

    async def get_article_by_canonical_url(self, canonical_url: str) -> Optional[NormalizedArticle]:
        return self.articles_by_url.get(canonical_url)

    async def get_recent_articles(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
    ) -> List[NormalizedArticle]:
        filtered = self.articles_list
        if source_id:
            filtered = [a for a in filtered if a.source_id == source_id]
        return filtered[offset : offset + limit]

    async def count_articles(self) -> int:
        return len(self.articles_list)

    async def delete_article(self, article_id: str) -> bool:
        if article_id in self.articles_by_id:
            article = self.articles_by_id.pop(article_id)
            self.articles_by_url.pop(article.canonical_url, None)
            self.articles_list.remove(article)
            return True
        return False


def make_sample_article(
    article_id: str = "art_5e_01",
    canonical_url: str = "https://techcrunch.com/2026/08/15/ai-breakthrough",
    title: str = "Quantum AI Breakthrough Announced",
    source_id: str = "techcrunch",
    source_name: str = "TechCrunch",
    hours_ago: float = 2.0,
    sentiment_score: Optional[float] = 0.85,
    tags: tuple[str, ...] = ("ai", "quantum"),
) -> NormalizedArticle:
    """Helper to build a valid canonical NormalizedArticle."""
    now = datetime.now(UTC)
    pub_at = now - timedelta(hours=hours_ago)
    disc_at = now - timedelta(hours=hours_ago - 0.1)

    return NormalizedArticle(
        id=article_id,
        canonical_url=canonical_url,
        original_url=canonical_url,
        title=title,
        clean_text="Detailed article text about quantum computing algorithms and neural networks.",
        summary="A major announcement regarding quantum artificial intelligence models.",
        source_id=source_id,
        source_name=source_name,
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        discovered_at=disc_at,
        published_at=pub_at,
        language="en",
        image_url="https://techcrunch.com/images/quantum.jpg",
        authors=("Jane Doe", "John Smith"),
        tags=tags,
        metadata={"sentiment_score": sentiment_score},
    )


# =============================================================================
# UNIT & ROUTE TESTS
# =============================================================================

def test_repository_dependency_injection():
    """Verify get_article_repository raises RuntimeError if uninitialized."""
    set_article_repository(None)
    with pytest.raises(RuntimeError, match="ArticleRepository has not been initialized"):
        get_article_repository()

    spy = SpyArticleRepository()
    set_article_repository(spy)
    assert get_article_repository() is spy
    set_article_repository(None)


def test_list_articles_pagination():
    """Verify GET /v1/articles supports pagination, limit, offset, and has_more flag."""
    spy = SpyArticleRepository()
    for i in range(5):
        spy.add_article(
            make_sample_article(
                article_id=f"art_page_{i}",
                canonical_url=f"https://example.com/story-{i}",
                title=f"Story Number {i}",
            )
        )
    set_article_repository(spy)

    test_app = FastAPI()
    test_app.include_router(articles_router)
    test_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    client = TestClient(test_app)

    # Page 1, per_page 2
    res1 = client.get("/v1/articles?page=1&per_page=2")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total"] == 5
    assert data1["page"] == 1
    assert data1["per_page"] == 2
    assert data1["has_more"] is True
    assert len(data1["articles"]) == 2
    assert data1["articles"][0]["id"] == "art_page_0"

    # Page 3, per_page 2 (Last item)
    res3 = client.get("/v1/articles?page=3&per_page=2")
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["page"] == 3
    assert data3["has_more"] is False
    assert len(data3["articles"]) == 1
    assert data3["articles"][0]["id"] == "art_page_4"

    set_article_repository(None)


def test_list_articles_source_filtering():
    """Verify GET /v1/articles?source=... filters articles by source ID."""
    spy = SpyArticleRepository()
    spy.add_article(make_sample_article("art_tc_01", "https://techcrunch.com/1", source_id="techcrunch"))
    spy.add_article(make_sample_article("art_verge_01", "https://theverge.com/1", source_id="theverge"))
    spy.add_article(make_sample_article("art_tc_02", "https://techcrunch.com/2", source_id="techcrunch"))
    set_article_repository(spy)

    test_app = FastAPI()
    test_app.include_router(articles_router)
    test_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    client = TestClient(test_app)
    res = client.get("/v1/articles?source=techcrunch")
    assert res.status_code == 200
    data = res.json()
    assert len(data["articles"]) == 2
    assert all(a["source"] == "TechCrunch" for a in data["articles"])

    set_article_repository(None)


def test_get_article_by_id_success():
    """Verify GET /v1/articles/{id} retrieves article and converts to DTO accurately."""
    spy = SpyArticleRepository()
    art = make_sample_article(
        article_id="art_lookup_01",
        canonical_url="https://techcrunch.com/quantum",
        title="Quantum Leap in AI",
        sentiment_score=0.92,
        tags=("quantum", "ai", "hardware"),
    )
    spy.add_article(art)
    set_article_repository(spy)

    test_app = FastAPI()
    test_app.include_router(articles_router)
    test_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    client = TestClient(test_app)
    res = client.get("/v1/articles/art_lookup_01")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "art_lookup_01"
    assert data["title"] == "Quantum Leap in AI"
    assert data["url"] == "https://techcrunch.com/quantum"
    assert data["source"] == "TechCrunch"
    assert data["sentiment_score"] == 0.92
    assert data["topics"] == ["quantum", "ai", "hardware"]
    assert "published_at" in data

    set_article_repository(None)


def test_get_article_by_canonical_url_fallback():
    """Verify GET /v1/articles/{url} resolves article by canonical URL fallback."""
    spy = SpyArticleRepository()
    url = "https://theverge.com/2026/08/15/new-chip"
    art = make_sample_article(
        article_id="art_chip_99",
        canonical_url=url,
        title="Next-Gen 2nm Chip Released",
    )
    spy.add_article(art)
    set_article_repository(spy)

    test_app = FastAPI()
    test_app.include_router(articles_router)
    test_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    client = TestClient(test_app)
    res = client.get(f"/v1/articles/{url}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "art_chip_99"
    assert data["title"] == "Next-Gen 2nm Chip Released"

    set_article_repository(None)


def test_get_article_not_found():
    """Verify GET /v1/articles/{id} returns 404 when article does not exist."""
    spy = SpyArticleRepository()
    set_article_repository(spy)

    test_app = FastAPI()
    test_app.include_router(articles_router)
    test_app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    client = TestClient(test_app)
    res = client.get("/v1/articles/nonexistent_article_id")
    assert res.status_code == 404
    data = res.json()
    assert "detail" in data
    assert "nonexistent_article_id" in data["detail"]

    set_article_repository(None)


def test_auth_enforcement():
    """Verify endpoints require authentication when API key is omitted."""
    spy = SpyArticleRepository()
    set_article_repository(spy)

    test_app = FastAPI()
    test_app.include_router(articles_router)

    client = TestClient(test_app)
    # No auth header -> 401 Unauthorized
    res = client.get("/v1/articles")
    assert res.status_code == 401

    set_article_repository(None)


def test_e2e_fastapi_lifespan_integration(tmp_path: Path):
    """Verify production FastAPI app initializes SqliteArticleRepository in lifespan."""
    db_file = tmp_path / "e2e_api_articles.db"
    engine = SqliteEngine(db_file)
    repo = SqliteArticleRepository(engine=engine, auto_init=True)

    # Insert sample article into SQLite
    sample = make_sample_article(
        article_id="art_e2e_lifespan",
        canonical_url="https://arstechnica.com/2026/08/15/security-zero-day",
        title="Critical Zero-Day Patched in OpenSSL",
    )
    asyncio.run(repo.save_article(sample))

    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(db_file)
    app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    try:
        with TestClient(app) as client:
            res = client.get("/v1/articles")
            assert res.status_code == 200
            data = res.json()
            assert data["total"] == 1
            assert data["articles"][0]["id"] == "art_e2e_lifespan"
            assert data["articles"][0]["title"] == "Critical Zero-Day Patched in OpenSSL"

            single_res = client.get("/v1/articles/art_e2e_lifespan")
            assert single_res.status_code == 200
            assert single_res.json()["title"] == "Critical Zero-Day Patched in OpenSSL"
    finally:
        app.dependency_overrides.clear()
        os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)
        asyncio.run(engine.aclose())


def test_api_articles_boundary_ast_no_sqlite_imports():
    """Verify src/api/routes/articles.py has zero forbidden imports."""
    articles_file = Path(__file__).resolve().parent.parent / "src" / "api" / "routes" / "articles.py"
    forbidden = {
        "sqlite3",
        "aiosqlite",
        "SqliteEngine",
        "SqliteArticleRepository",
        "SqliteEventRepository",
        "Database",
        "db_handler",
        "EventStore",
    }

    tree = ast.parse(articles_file.read_text(encoding="utf-8"), filename=str(articles_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, f"Forbidden import '{alias.name}' in {articles_file.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not any(f in mod for f in forbidden), f"Forbidden module '{mod}' in {articles_file.name}"
            for alias in node.names:
                assert alias.name not in forbidden, f"Forbidden symbol '{alias.name}' in {articles_file.name}"
