"""
Unit & Integration Tests for Full-Text Search API Endpoint.
Location: tests/test_api_article_search.py
"""

from __future__ import annotations

import ast
from datetime import datetime, UTC
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.main import verify_api_key
from src.api.routes.articles import (
    router as articles_router,
    set_article_repository,
)
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import ArticleSearchResult, NormalizedArticle
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine

REPO_ROOT = Path(__file__).parent.parent


def _make_article(
    url: str,
    title: str,
    clean_text: str = "",
    summary: str = "",
    source_id: str = "src_tech",
    tags: tuple = (),
) -> NormalizedArticle:
    return NormalizedArticle.create(
        canonical_url=url,
        original_url=url,
        title=title,
        clean_text=clean_text,
        summary=summary,
        source_id=source_id,
        source_name="Tech Source",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        discovered_at=datetime.now(UTC),
        tags=tags,
    )


class TestArticleSearchAPI(unittest.TestCase):
    """Test suite for GET /v1/articles/search endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_api_fts.db"
        cls.engine = SqliteEngine(cls.db_path)
        
        # Initialize schema synchronously via loop
        import asyncio
        asyncio.run(cls.engine.initialize_schema())
        cls.repo = SqliteArticleRepository(cls.engine, auto_init=False)
        
        # Populate sample articles
        art1 = _make_article(
            url="https://example.com/quantum-crypto",
            title="Post-Quantum Cryptography Standards Published",
            clean_text="NIST releases definitive post-quantum encryption algorithms for public deployment.",
            summary="NIST finalizes post-quantum encryption standards.",
            source_id="src_nist_advisory",
            tags=("security", "cryptography", "quantum"),
        )
        art2 = _make_article(
            url="https://example.com/silicon-ai",
            title="Silicon Photonic Accelerator Chips in Data Centers",
            clean_text="Optical interconnects delivering 10x throughput for large language models.",
            summary="Optical photonics breakthrough for LLM training clusters.",
            source_id="src_hardware_daily",
            tags=("hardware", "photonics", "ai"),
        )
        asyncio.run(cls.repo.save_articles([art1, art2]))

        # Setup test app
        cls.app = FastAPI()
        cls.app.include_router(articles_router)
        cls.app.dependency_overrides[verify_api_key] = lambda: {"user": "test_admin"}
        set_article_repository(cls.repo)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        import asyncio
        asyncio.run(cls.engine.aclose())
        cls.temp_dir.cleanup()
        set_article_repository(None)

    def test_search_success_with_snippets(self):
        res = self.client.get("/v1/articles/search?q=Cryptography")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["query"], "Cryptography")
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)
        self.assertIn("Post-Quantum Cryptography", data["results"][0]["article"]["title"])
        self.assertGreater(data["results"][0]["relevance_score"], 0.0)
        self.assertIn("<mark>", data["results"][0]["snippet"])

    def test_search_with_source_filter(self):
        res = self.client.get("/v1/articles/search?q=quantum&source=src_nist_advisory")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 1)

        # Mismatched source filter returns 0
        res_mismatch = self.client.get("/v1/articles/search?q=quantum&source=src_other")
        self.assertEqual(res_mismatch.status_code, 200)
        self.assertEqual(res_mismatch.json()["count"], 0)

    def test_search_with_tag_filter(self):
        res = self.client.get("/v1/articles/search?q=Photonic&tag=photonics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 1)

    def test_search_missing_query_param_422(self):
        res = self.client.get("/v1/articles/search")
        self.assertEqual(res.status_code, 422)

    def test_articles_router_ast_zero_storage_driver_imports(self):
        """Ensure articles API route never imports SQLite or concrete repositories."""
        api_file = REPO_ROOT / "src" / "api" / "routes" / "articles.py"
        tree = ast.parse(api_file.read_text(encoding="utf-8"), filename=str(api_file))

        forbidden = ("sqlite3", "aiosqlite", "src.storage.sqlite_engine", "src.storage.sqlite_article_repository")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for f in forbidden:
                        self.assertFalse(
                            alias.name == f or alias.name.startswith(f + "."),
                            f"articles.py illegally imports {alias.name}",
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for f in forbidden:
                        self.assertFalse(
                            node.module == f or node.module.startswith(f + "."),
                            f"articles.py illegally imports from {node.module}",
                        )
