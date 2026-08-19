"""
Unit & Integration Tests for SQLite FTS5 Full-Text Search Integration.
Location: tests/test_fts5_article_search.py
"""

import asyncio
from datetime import datetime, UTC
from pathlib import Path
import tempfile
import unittest

import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import ArticleSearchResult, NormalizedArticle
from src.storage.fts_sanitizer import sanitize_fts5_query
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine


def _make_article(
    url: str,
    title: str,
    clean_text: str = "",
    summary: str = "",
    tags: tuple = (),
    source_id: str = "src_tech",
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


class TestFTS5Sanitizer(unittest.TestCase):
    """Test suite for FTS5 query sanitizer."""

    def test_sanitize_simple_terms(self):
        self.assertEqual(sanitize_fts5_query("quantum computing"), '"quantum"* "computing"*')

    def test_sanitize_exact_phrase(self):
        self.assertEqual(sanitize_fts5_query('"deep learning"'), '"deep learning"')

    def test_sanitize_dangerous_chars_and_operators(self):
        fuzz_query = ':::***^^^{}()[]~+-<>="malicious operator" AND OR NOT'
        sanitized = sanitize_fts5_query(fuzz_query)
        self.assertIsNotNone(sanitized)
        self.assertNotIn(":", sanitized)
        self.assertNotIn("^", sanitized)
        self.assertNotIn("*", sanitized.replace('"*', ''))
        self.assertIn('"malicious operator"', sanitized)

    def test_sanitize_empty_and_whitespace(self):
        self.assertIsNone(sanitize_fts5_query(""))
        self.assertIsNone(sanitize_fts5_query("   "))
        self.assertIsNone(sanitize_fts5_query(":::***^^^"))


class TestFTS5ArticleSearch(unittest.IsolatedAsyncioTestCase):
    """Comprehensive test suite for FTS5 full-text indexing, BM25 ranking, and ACID sync."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_fts5.db"
        self.engine = SqliteEngine(self.db_path)
        await self.engine.initialize_schema()
        self.repo = SqliteArticleRepository(self.engine, auto_init=False)

    async def asyncTearDown(self):
        await self.engine.aclose()
        self.temp_dir.cleanup()

    async def test_insert_triggers_fts5_searchable(self):
        article = _make_article(
            url="https://example.com/quantum-breakthrough",
            title="Quantum Processor Reaches 1000 Qubits",
            clean_text="Superconducting qubits achieved unprecedented coherence times in lab tests.",
            summary="New milestone in quantum hardware architecture.",
            tags=("quantum", "hardware"),
        )
        await self.repo.save_article(article)

        results = await self.repo.search_articles_fts("quantum")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].article.id, article.id)
        self.assertIn("1000 Qubits", results[0].article.title)
        self.assertGreater(results[0].relevance_score, 0.0)

    async def test_update_triggers_fts5_sync(self):
        article = _make_article(
            url="https://example.com/dynamic-article",
            title="Initial Title About Robotics",
            clean_text="Autonomous robots navigating warehouses.",
        )
        await self.repo.save_article(article)

        # Confirm findable by robotics
        results = await self.repo.search_articles_fts("robotics")
        self.assertEqual(len(results), 1)

        # Update article to focus on Biotechnology
        updated_article = _make_article(
            url="https://example.com/dynamic-article",
            title="Updated Title About Biotechnology",
            clean_text="CRISPR gene editing breakthroughs in cell therapies.",
        )
        await self.repo.save_article(updated_article)

        # Old term should return 0 results
        old_results = await self.repo.search_articles_fts("robotics")
        self.assertEqual(len(old_results), 0)

        # New term should return 1 result
        new_results = await self.repo.search_articles_fts("biotechnology")
        self.assertEqual(len(new_results), 1)
        self.assertEqual(new_results[0].article.title, "Updated Title About Biotechnology")

    async def test_delete_triggers_fts5_sync(self):
        article = _make_article(
            url="https://example.com/to-delete",
            title="Transient Microchip Announcement",
            clean_text="Details regarding legacy semiconductor fabrication.",
        )
        await self.repo.save_article(article)
        self.assertEqual(len(await self.repo.search_articles_fts("microchip")), 1)

        # Delete article
        deleted = await self.repo.delete_article(article.id)
        self.assertTrue(deleted)

        # FTS5 should return zero matches
        self.assertEqual(len(await self.repo.search_articles_fts("microchip")), 0)

    async def test_transaction_rollback_preserves_consistency(self):
        article = _make_article(
            url="https://example.com/rollback-target",
            title="Secret Internal Architecture Draft",
            clean_text="Proprietary neural accelerator benchmarks.",
        )

        # Attempt transaction that inserts and then rolls back
        try:
            async with self.engine.transaction() as conn:
                params = self.repo._article_to_params(article)
                sql = """
                INSERT INTO canonical_articles (
                    id, canonical_url, original_url, title, clean_text, summary,
                    source_id, source_name, source_tier, zombie_species,
                    discovered_at, published_at, language, image_url, authors, tags, metadata
                ) VALUES (
                    :id, :canonical_url, :original_url, :title, :clean_text, :summary,
                    :source_id, :source_name, :source_tier, :zombie_species,
                    :discovered_at, :published_at, :language, :image_url, :authors, :tags, :metadata
                );
                """
                await conn.execute(sql, params)
                # Force rollback via deliberate error
                raise RuntimeError("Simulated transaction crash")
        except RuntimeError:
            pass

        # Zero ghost records in FTS5
        results = await self.repo.search_articles_fts("accelerator")
        self.assertEqual(len(results), 0)

    async def test_restart_persists_fts5_index(self):
        article = _make_article(
            url="https://example.com/persistent-ai",
            title="Neural Architecture Search Optimization",
            clean_text="Evolutionary search algorithms discovering efficient transformer topologies.",
        )
        await self.repo.save_article(article)
        await self.engine.aclose()

        # Reopen with fresh engine connection
        new_engine = SqliteEngine(self.db_path)
        new_repo = SqliteArticleRepository(new_engine, auto_init=False)
        try:
            results = await new_repo.search_articles_fts("transformer")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].article.id, article.id)
        finally:
            await new_engine.aclose()

    async def test_bm25_ranking_prioritizes_title_matches(self):
        # Article 1 has query keyword in title (Weight 5.0)
        art1 = _make_article(
            url="https://example.com/rust-compiler",
            title="Rust Compiler Release 2.0",
            clean_text="General software development tooling updates.",
        )
        # Article 2 has query keyword only deep in body (Weight 1.0)
        art2 = _make_article(
            url="https://example.com/other-news",
            title="Monthly Technology Digest",
            clean_text="We also tested a small library written in Rust.",
        )
        await self.repo.save_articles([art2, art1])

        results = await self.repo.search_articles_fts("Rust")
        self.assertEqual(len(results), 2)
        # Title match must rank first
        self.assertEqual(results[0].article.id, art1.id)

    async def test_snippet_highlights_keywords(self):
        article = _make_article(
            url="https://example.com/security-advisory",
            title="Critical Kernel Vulnerability Discovered",
            clean_text="A zero-day memory corruption flaw allows remote arbitrary code execution.",
            summary="Emergency patch released for Linux kernel systems.",
        )
        await self.repo.save_article(article)

        results = await self.repo.search_articles_fts("Vulnerability")
        self.assertEqual(len(results), 1)
        self.assertIn("<mark>", results[0].snippet)
        self.assertIn("</mark>", results[0].snippet)

    async def test_concurrent_reads_and_writes_under_wal(self):
        articles = [
            _make_article(
                url=f"https://example.com/concurrent-{i}",
                title=f"Parallel Processing Scale Article {i}",
                clean_text=f"Distributed systems executing concurrent transactions at worker shard {i}.",
            )
            for i in range(20)
        ]

        async def writer():
            for a in articles:
                await self.repo.save_article(a)
                await asyncio.sleep(0.01)

        async def reader():
            found_counts = []
            for _ in range(15):
                res = await self.repo.search_articles_fts("Distributed")
                found_counts.append(len(res))
                await asyncio.sleep(0.01)
            return found_counts

        _, counts = await asyncio.gather(writer(), reader())
        self.assertGreater(counts[-1], 0)

    async def test_source_id_and_tag_filtering(self):
        art1 = _make_article(
            url="https://example.com/source-a",
            title="Silicon Photonics in High Performance Computing",
            source_id="src_hpc_weekly",
            tags=("hardware", "optics"),
        )
        art2 = _make_article(
            url="https://example.com/source-b",
            title="Silicon Carbide Power Semiconductors",
            source_id="src_semiconductor_today",
            tags=("energy", "power"),
        )
        await self.repo.save_articles([art1, art2])

        # Filter by source_id
        res_src_a = await self.repo.search_articles_fts("Silicon", source_id="src_hpc_weekly")
        self.assertEqual(len(res_src_a), 1)
        self.assertEqual(res_src_a[0].article.id, art1.id)

        # Filter by tag
        res_tag_power = await self.repo.search_articles_fts("Silicon", tag="power")
        self.assertEqual(len(res_tag_power), 1)
        self.assertEqual(res_tag_power[0].article.id, art2.id)

    async def test_pagination_limit_offset(self):
        articles = [
            _make_article(
                url=f"https://example.com/page-{i}",
                title=f"Autonomous Agent Fleet Architecture {i}",
                clean_text="Multi-agent orchestration and consensus protocols.",
            )
            for i in range(10)
        ]
        await self.repo.save_articles(articles)

        # Fetch page 1 (limit 3, offset 0)
        page1 = await self.repo.search_articles_fts("Autonomous", limit=3, offset=0)
        self.assertEqual(len(page1), 3)

        # Fetch page 2 (limit 3, offset 3)
        page2 = await self.repo.search_articles_fts("Autonomous", limit=3, offset=3)
        self.assertEqual(len(page2), 3)

        # Page 1 and Page 2 IDs must not overlap
        page1_ids = {r.article.id for r in page1}
        page2_ids = {r.article.id for r in page2}
        self.assertEqual(len(page1_ids & page2_ids), 0)
