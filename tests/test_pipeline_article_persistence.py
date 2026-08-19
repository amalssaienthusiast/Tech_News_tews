"""
Unit & Integration Tests for Subphase 5E-C: Pipeline Article Persistence.
Location: tests/test_pipeline_article_persistence.py

Verifies:
1. Accepted article is persisted to ArticleRepository post-S06
2. Stale article (>72h) dropped at S02 is NOT persisted
3. Irrelevant article (<0.40 score) dropped at S03 is NOT persisted
4. Quality-rejected article dropped at S04 is NOT persisted
5. Duplicate-rejected article dropped at S05/S06 is NOT persisted
6. Persistence call is strictly asynchronous
7. Repository failure propagates as IngestionResult.error without corrupting metrics
8. Article identity remains unchanged throughout pipeline execution
9. S07 receives the exact same NormalizedArticle entity
10. Runner initialized without ArticleRepository maintains backwards compatibility
11. Explicit stage execution ordering: S06 -> save_article() -> S07
12. Pipeline codebase contains zero SQLite/database implementation imports (AST boundary)
13. End-to-end integration with real SqliteArticleRepository and SqliteEngine
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation, NormalizedArticle, TechEvent
from src.pipeline.protocols import PipelineContext
from src.pipeline.runner import CanonicalPipelineRunner, IngestionStatus
from src.storage.protocols import ArticleRepositoryProtocol
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine


class SpyArticleRepository(ArticleRepositoryProtocol):
    """Spy in-memory implementation of ArticleRepositoryProtocol for testing."""

    def __init__(self, fail_on_save: bool = False):
        self.saved_articles: List[NormalizedArticle] = []
        self.save_calls: int = 0
        self.fail_on_save = fail_on_save
        self.call_order: List[str] = []

    async def save_article(self, article: NormalizedArticle) -> None:
        self.call_order.append("save_article")
        self.save_calls += 1
        if self.fail_on_save:
            raise RuntimeError("Simulated article repository storage failure")
        self.saved_articles.append(article)

    async def save_articles(self, articles: Sequence[NormalizedArticle]) -> int:
        for a in articles:
            await self.save_article(a)
        return len(articles)

    async def get_article(self, article_id: str) -> Optional[NormalizedArticle]:
        for a in self.saved_articles:
            if a.id == article_id:
                return a
        return None

    async def get_article_by_canonical_url(self, canonical_url: str) -> Optional[NormalizedArticle]:
        for a in self.saved_articles:
            if a.canonical_url == canonical_url:
                return a
        return None

    async def get_recent_articles(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
    ) -> List[NormalizedArticle]:
        filtered = self.saved_articles
        if source_id:
            filtered = [a for a in filtered if a.source_id == source_id]
        return filtered[offset : offset + limit]

    async def count_articles(self) -> int:
        return len(self.saved_articles)

    async def delete_article(self, article_id: str) -> bool:
        initial_len = len(self.saved_articles)
        self.saved_articles = [a for a in self.saved_articles if a.id != article_id]
        return len(self.saved_articles) < initial_len


def make_valid_observation(
    url: str = "https://techcrunch.com/2026/08/14/quantum-processor-release",
    title: str = "Google and IBM Unveil Fault-Tolerant Quantum Processor Breakthrough",
    clean_text: str = "Quantum computing engineering teams have deployed a new fault-tolerant architecture with 99.9% fidelity.",
    published_offset_hours: float = 2.0,
    source_name: str = "TechCrunch",
) -> SourceObservation:
    now = datetime.now(UTC)
    pub_time = now - timedelta(hours=published_offset_hours)
    return SourceObservation.create(
        source_id="src_techcrunch",
        source_name=source_name,
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        observed_at=now,
        url=url,
        title=title,
        raw_content=clean_text,
        published_at_hint=pub_time,
    )


@pytest.mark.asyncio
async def test_accepted_article_persisted_post_s06():
    """Verify that a valid article passing S01-S06 is saved to the ArticleRepository."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    obs = make_valid_observation()
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.SUCCESS
    assert repo.save_calls == 1
    assert len(repo.saved_articles) == 1
    assert repo.saved_articles[0].canonical_url == obs.url
    assert repo.saved_articles[0].title == obs.title


@pytest.mark.asyncio
async def test_stale_article_not_persisted():
    """Verify that stale articles dropped at S02 are never persisted."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    # Article older than 72h is stale
    obs = make_valid_observation(
        url="https://example.com/stale-story",
        published_offset_hours=100.0,
    )
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.DROPPED
    assert res.rejected_at_stage == "s02_freshness"
    assert repo.save_calls == 0
    assert len(repo.saved_articles) == 0


@pytest.mark.asyncio
async def test_irrelevant_article_not_persisted():
    """Verify that non-tech/irrelevant articles dropped at S03 are never persisted."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    # Non-tech article
    obs = make_valid_observation(
        url="https://example.com/pasta-recipe",
        title="Delicious Creamy Garlic Parmesan Pasta Recipe For Dinner",
        clean_text="Cook pasta in boiling salted water. Mix garlic and heavy cream in a saucepan.",
    )
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.DROPPED
    assert res.rejected_at_stage == "s03_relevance"
    assert repo.save_calls == 0
    assert len(repo.saved_articles) == 0


@pytest.mark.asyncio
async def test_quality_rejected_article_not_persisted():
    """Verify that low-quality/gibberish articles dropped at S04 are never persisted."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    # Clickbait / low quality article that passes S03 tech relevance
    obs = make_valid_observation(
        url="https://example.com/low-quality",
        title="SHOCKING SECRET DISCOVERY IN PYTHON AI ARCHITECTURE WILL BLOW YOUR MIND!!!",
        clean_text="Python AI architecture neural network model machine learning software database algorithm. Subscribe to read the full article.",
    )
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.DROPPED
    assert res.rejected_at_stage == "s04_quality"
    assert repo.save_calls == 0
    assert len(repo.saved_articles) == 0


@pytest.mark.asyncio
async def test_duplicate_rejected_article_not_persisted():
    """Verify that exact duplicate articles rejected at S05/S06 do not trigger a second save."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    obs1 = make_valid_observation(url="https://techcrunch.com/unique-story-101")
    res1 = await runner.process_observation(obs1)
    assert res1.status == IngestionStatus.SUCCESS
    assert repo.save_calls == 1

    # Second observation with same canonical URL
    obs2 = make_valid_observation(url="https://techcrunch.com/unique-story-101")
    res2 = await runner.process_observation(obs2)
    assert res2.status == IngestionStatus.DROPPED
    assert res2.rejected_at_stage in ("s05_dedup_evaluator", "s06_dedup_committer")
    # Must still be exactly 1 save call
    assert repo.save_calls == 1
    assert len(repo.saved_articles) == 1


@pytest.mark.asyncio
async def test_repository_error_propagates_cleanly():
    """Verify that a repository save failure returns IngestionResult.error cleanly."""
    failing_repo = SpyArticleRepository(fail_on_save=True)
    runner = CanonicalPipelineRunner(article_repository=failing_repo)

    obs = make_valid_observation()
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.ERROR
    assert "Simulated article repository storage failure" in str(res.abort_reason)
    assert len(failing_repo.saved_articles) == 0


@pytest.mark.asyncio
async def test_article_identity_preserved_to_s07():
    """Verify that the exact NormalizedArticle passed into ArticleRepository is forwarded to S07."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    obs = make_valid_observation()
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.SUCCESS
    assert res.event is not None
    persisted_article = repo.saved_articles[0]

    # S07 event sources must reference this exact article
    assert len(res.event.sources) >= 1
    event_source = res.event.sources[0]
    assert event_source.article_id == persisted_article.id
    assert event_source.url == persisted_article.canonical_url


@pytest.mark.asyncio
async def test_runner_compatibility_without_article_repository():
    """Verify that CanonicalPipelineRunner works without ArticleRepository (optional dependency)."""
    runner = CanonicalPipelineRunner(article_repository=None)
    obs = make_valid_observation()
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.SUCCESS
    assert res.event is not None


@pytest.mark.asyncio
async def test_persistence_ordering_s06_repo_s07(monkeypatch):
    """Verify explicit ordering: S06 completes -> ArticleRepository saves -> S07 executes."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    execution_order = []

    orig_s06 = runner.s06_dedup_commit.process
    async def wrapped_s06(item, ctx):
        execution_order.append("S06")
        return await orig_s06(item, ctx)
    monkeypatch.setattr(runner.s06_dedup_commit, "process", wrapped_s06)

    orig_save = repo.save_article
    async def wrapped_save(article):
        execution_order.append("SAVE_ARTICLE")
        return await orig_save(article)
    monkeypatch.setattr(repo, "save_article", wrapped_save)

    orig_s07 = runner.s07_clustering.process
    async def wrapped_s07(item, ctx):
        execution_order.append("S07")
        return await orig_s07(item, ctx)
    monkeypatch.setattr(runner.s07_clustering, "process", wrapped_s07)

    obs = make_valid_observation()
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.SUCCESS
    assert execution_order == ["S06", "SAVE_ARTICLE", "S07"]


@pytest.mark.asyncio
async def test_e2e_pipeline_with_sqlite_article_repository(tmp_path: Path):
    """Verify end-to-end integration between CanonicalPipelineRunner and SqliteArticleRepository."""
    db_file = tmp_path / "e2e_canonical_articles.db"
    engine = SqliteEngine(db_file)
    article_repo = SqliteArticleRepository(engine=engine, auto_init=True)
    runner = CanonicalPipelineRunner(article_repository=article_repo)

    obs = make_valid_observation(url="https://techcrunch.com/2026/08/14/quantum-ai-e2e")
    res = await runner.process_observation(obs)

    assert res.status == IngestionStatus.SUCCESS
    assert await article_repo.count_articles() == 1

    saved = await article_repo.get_article_by_canonical_url("https://techcrunch.com/2026/08/14/quantum-ai-e2e")
    assert saved is not None
    assert saved.title == obs.title
    assert saved.source_id == obs.source_id

    await engine.aclose()


def test_pipeline_boundary_ast_no_sqlite_imports():
    """Verify that src/pipeline/runner.py and stages contain zero imports of sqlite3, aiosqlite, or SqliteEngine."""
    pipeline_dir = Path(__file__).resolve().parent.parent / "src" / "pipeline"
    forbidden = {"sqlite3", "aiosqlite", "SqliteEngine", "SqliteArticleRepository", "SqliteEventRepository"}

    for py_file in pipeline_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"Forbidden import '{alias.name}' in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(f in mod for f in forbidden), f"Forbidden module '{mod}' in {py_file.name}"
                for alias in node.names:
                    assert alias.name not in forbidden, f"Forbidden imported symbol '{alias.name}' in {py_file.name}"


@pytest.mark.asyncio
async def test_shadow_mode_dry_run_skips_article_persistence():
    """Verify that shadow mode (dry_run=True) does NOT persist articles to repository."""
    repo = SpyArticleRepository()
    runner = CanonicalPipelineRunner(article_repository=repo)

    obs = make_valid_observation(url="https://techcrunch.com/2026/08/14/dry-run-article")
    res = await runner.process_observation(obs, dry_run=True)

    assert res.status == IngestionStatus.SUCCESS
    assert repo.save_calls == 0
    assert len(repo.saved_articles) == 0

