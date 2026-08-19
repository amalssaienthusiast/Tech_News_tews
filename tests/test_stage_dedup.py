"""
Unit Tests for Stages 5 and 6: Deduplication Evaluator & Committer (Subphase 3D).
Location: tests/test_stage_dedup.py
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, UTC
import pytest

from src.domain.enums import DedupAction, QualityCheckLevel, SourceTier, ZombieSpecies
from src.domain.models import NormalizedArticle, QualityReport, DedupDecision
from src.domain.validators import DomainValidationError
from src.pipeline.protocols import PipelineStage, PipelineContext
from src.pipeline.stages.s05_dedup_evaluator import (
    DedupIndex,
    DedupEvaluator,
    extract_title_shingles,
    compute_jaccard_similarity,
)
from src.pipeline.stages.s06_dedup_committer import DedupCommitter


@pytest.fixture
def shared_index():
    return DedupIndex(max_capacity=100)


@pytest.fixture
def evaluator(shared_index):
    return DedupEvaluator(shared_index)


@pytest.fixture
def committer(shared_index):
    return DedupCommitter(shared_index)


@pytest.fixture
def make_article():
    def _factory(
        url="https://techcrunch.com/2026/08/14/ai-breakthrough",
        title="OpenAI Releases New Deep Learning Architecture",
        source_id="tc_feed",
    ):
        return NormalizedArticle.create(
            canonical_url=url,
            original_url=url,
            title=title,
            clean_text="Body content discussing neural network models.",
            summary="New deep learning architecture released.",
            source_id=source_id,
            source_name="TechCrunch",
            source_tier=SourceTier.TIER_1_PREMIUM,
            zombie_species=ZombieSpecies.RSS,
        )
    return _factory


# =============================================================================
# 1. PROTOCOL COMPLIANCE TESTS
# =============================================================================

def test_dedup_stages_protocol_compliance(evaluator, committer):
    assert isinstance(evaluator, PipelineStage)
    assert evaluator.name == "dedup_evaluator"
    assert evaluator.stage_number == 5

    assert isinstance(committer, PipelineStage)
    assert committer.name == "dedup_committer"
    assert committer.stage_number == 6


# =============================================================================
# 2. CRITICAL REGRESSION TEST: DEDUP POISONING PREVENTION
# =============================================================================

@pytest.mark.asyncio
async def test_dedup_poisoning_prevention_flow(shared_index, make_article):
    """
    Critical Architecture Test:
    A rejected low-quality article must NOT poison the dedup cache.
    A subsequent high-quality article with identical identity must be accepted and committed.
    """
    evaluator = DedupEvaluator(shared_index)
    committer = DedupCommitter(shared_index)
    article_url = "https://wired.com/story/cybersecurity-zero-day"
    assert len(shared_index) == 0

    # -------------------------------------------------------------
    # 1. Bad/Low-Quality Article Arrives
    # -------------------------------------------------------------
    bad_article = make_article(url=article_url, title="Clickbait Broken Scraping")
    ctx1 = PipelineContext()

    # Step A: Evaluate
    eval_res1 = await evaluator.process(bad_article, ctx1)
    assert eval_res1 is not None
    _, decision1 = eval_res1
    assert decision1.action == DedupAction.ACCEPTED
    assert decision1.is_duplicate is False
    assert len(shared_index) == 0  # Read-only!

    # Step B: Quality Gate Rejects It
    bad_report = QualityReport(
        article_id=bad_article.id,
        is_passed=False,
        quality_score=0.20,
        relevance_score=0.80,
        rejection_reasons=("CLICKBAIT_HEADLINE", "EXTREMELY_SHORT_CONTENT"),
    )
    ctx1.set("quality_report", bad_report)

    # Step C: Dedup Committer Skips It
    commit_res1 = await committer.process(bad_article, ctx1)
    assert commit_res1 is None
    assert ctx1.get("dedup_committed") is False
    assert len(shared_index) == 0  # Still zero! Bad article did NOT poison index.

    # -------------------------------------------------------------
    # 2. Good/High-Quality Article with Same URL Arrives Later
    # -------------------------------------------------------------
    good_article = make_article(url=article_url, title="Critical Zero-Day Patched in Linux Kernel")
    ctx2 = PipelineContext()

    # Step A: Evaluate (Must STILL be accepted because bad one wasn't committed)
    eval_res2 = await evaluator.process(good_article, ctx2)
    assert eval_res2 is not None
    _, decision2 = eval_res2
    assert decision2.action == DedupAction.ACCEPTED
    assert decision2.is_duplicate is False

    # Step B: Quality Gate Passes It
    good_report = QualityReport(
        article_id=good_article.id,
        is_passed=True,
        quality_score=0.90,
        relevance_score=0.95,
        rejection_reasons=(),
    )
    ctx2.set("quality_report", good_report)

    # Step C: Dedup Committer Successfully Commits It
    commit_res2 = await committer.process(good_article, ctx2)
    assert commit_res2 is not None
    assert ctx2.get("dedup_committed") is True
    assert len(shared_index) == 1

    # -------------------------------------------------------------
    # 3. Third Duplicate Article Arrives
    # -------------------------------------------------------------
    ctx3 = PipelineContext()
    eval_res3 = await evaluator.process(good_article, ctx3)
    assert eval_res3 is None  # Evaluator detects duplicate and aborts
    assert ctx3.is_aborted is True
    decision3: DedupDecision = ctx3.get("dedup_decision")
    assert decision3.action == DedupAction.EXACT_URL_DUPLICATE
    assert decision3.is_duplicate is True


# =============================================================================
# 3. SIMILAR TITLE DEDUPLICATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_similar_title_deduplication(shared_index, make_article):
    evaluator = DedupEvaluator(shared_index)
    committer = DedupCommitter(shared_index)

    # Commit first story
    art1 = make_article(
        url="https://techcrunch.com/2026/08/14/openai-gpt5",
        title="OpenAI Officially Unveils GPT-5 Reasoning Model With Multimodal Capabilities",
    )
    ctx1 = PipelineContext()
    ctx1.set("quality_report", QualityReport(
        article_id=art1.id, is_passed=True, quality_score=0.9, relevance_score=0.9
    ))
    await evaluator.process(art1, ctx1)
    await committer.process(art1, ctx1)

    # Second story with different URL but highly similar title
    art2 = make_article(
        url="https://theverge.com/2026/08/14/openai-gpt5-launch",
        title="OpenAI Officially Unveils GPT-5 Reasoning Model With Multimodal Features",
    )
    ctx2 = PipelineContext()
    res = await evaluator.process(art2, ctx2)
    assert res is None
    assert ctx2.is_aborted is True

    decision: DedupDecision = ctx2.get("dedup_decision")
    assert decision.action == DedupAction.SIMILAR_TITLE_DUPLICATE
    assert decision.is_duplicate is True
    assert decision.matched_article_id == art1.id
    assert decision.similarity_score >= 0.70


# =============================================================================
# 4. COMMITER IDEMPOTENCY & READ-ONLY EVALUATION GUARANTEES
# =============================================================================

@pytest.mark.asyncio
async def test_evaluator_is_strictly_read_only(evaluator, make_article):
    index = evaluator.index
    article = make_article()
    for _ in range(50):
        ctx = PipelineContext()
        await evaluator.process(article, ctx)
        assert len(index) == 0


@pytest.mark.asyncio
async def test_committer_is_idempotent(committer, make_article):
    index = committer.index
    article = make_article()
    ctx = PipelineContext()
    ctx.set("quality_report", QualityReport(
        article_id=article.id, is_passed=True, quality_score=0.9, relevance_score=0.9
    ))
    ctx.set("dedup_decision", DedupDecision(
        article_id=article.id,
        action=DedupAction.ACCEPTED,
        is_duplicate=False,
        canonical_url=article.canonical_url,
    ))

    res1 = await committer.process(article, ctx)
    assert res1 is not None
    assert len(index) == 1

    # Second commit of exact same item
    res2 = await committer.process(article, ctx)
    assert res2 is not None
    assert len(index) == 1


# =============================================================================
# 5. BOUNDED CAPACITY / LRU EVICTION TESTS
# =============================================================================

def test_dedup_index_bounded_capacity():
    small_index = DedupIndex(max_capacity=5)
    for i in range(10):
        small_index.commit(
            canonical_url=f"https://example.com/story/{i}",
            title=f"Unique Story Number {i} in Tech World",
            article_id=f"art_{i}",
        )
    assert len(small_index) == 5
    # Story 0 should be evicted, Story 9 should be present
    dec_old = small_index.evaluate("https://example.com/story/0", "Unique Story Number 0", "art_0")
    assert dec_old.action == DedupAction.ACCEPTED  # Was evicted

    dec_new = small_index.evaluate("https://example.com/story/9", "Unique Story Number 9", "art_9")
    assert dec_new.action == DedupAction.EXACT_URL_DUPLICATE  # Still in cache


# =============================================================================
# 6. THREAD-SAFETY / CONCURRENCY TESTS
# =============================================================================

def test_concurrent_evaluation_and_commit():
    index = DedupIndex(max_capacity=500)

    def worker(worker_id: int):
        for i in range(20):
            url = f"https://example.com/worker_{worker_id}/story_{i}"
            title = f"UniqueSubject{worker_id} TechDomain{i} Innovation{worker_id}_{i} Architecture"
            art_id = f"art_{worker_id}_{i}"
            # evaluate
            dec = index.evaluate(url, title, art_id)
            assert dec.action == DedupAction.ACCEPTED
            # commit
            index.commit(url, title, art_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, w) for w in range(8)]
        for f in futures:
            f.result()

    assert len(index) == 160


# =============================================================================
# 7. INPUT VALIDATION & INDEX CLEAR TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_dedup_stages_reject_invalid_inputs(evaluator, committer):
    ctx = PipelineContext()
    with pytest.raises(DomainValidationError, match="DedupEvaluator expects NormalizedArticle"):
        await evaluator.process("invalid_input", ctx)  # type: ignore

    with pytest.raises(DomainValidationError, match="DedupCommitter expects NormalizedArticle"):
        await committer.process("invalid_input", ctx)  # type: ignore


def test_dedup_index_clear():
    index = DedupIndex()
    index.commit("https://example.com/item/1", "Test Title", "art_1")
    assert len(index) == 1
    index.clear()
    assert len(index) == 0
