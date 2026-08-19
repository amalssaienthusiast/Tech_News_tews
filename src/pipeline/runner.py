"""
Canonical Pipeline Runner.
Location: src/pipeline/runner.py

Orchestrates sequential execution of the 11 canonical pipeline stages:
S01: ObservationNormalizer (SourceObservation -> NormalizedArticle)
S02: FreshnessEvaluator (NormalizedArticle -> NormalizedArticle)
S03: TechRelevanceFilter (NormalizedArticle -> NormalizedArticle)
S04: QualityGate (NormalizedArticle -> (NormalizedArticle, QualityReport))
S05: DedupEvaluator (NormalizedArticle -> (NormalizedArticle, DedupDecision))
S06: DedupCommitter (NormalizedArticle -> NormalizedArticle)
S07: EventClusterer (NormalizedArticle -> TechEvent)
S08: ScoringEngine (TechEvent -> TechEvent)
S09: EnrichmentStage (TechEvent -> TechEvent)
S10: PersistenceStage (TechEvent -> TechEvent)
S11: PublicationStage (TechEvent -> TechEvent)

Key Architectural Invariants:
- Execution-scoped PipelineContext per item (zero cross-item context leakage)
- Bounded concurrency with asyncio.Semaphore(16)
- Comprehensive error isolation (one malformed article never crashes or blocks runner)
- Rich IngestionResult reporting
- Pure shadow mode dry-run support (S01–S08 telemetry only, S09–S11 skipped)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Dict, List, Optional

from ..domain.models import SourceObservation, NormalizedArticle, TechEvent
from ..engine.publication_bus import PublicationBus, get_publication_bus
from ..storage.protocols import ArticleRepositoryProtocol, EventRepositoryProtocol
from .protocols import PipelineContext
from .stages.s01_normalizer import ObservationNormalizer
from .stages.s02_freshness import FreshnessEvaluator
from .stages.s03_relevance import TechRelevanceFilter
from .stages.s04_quality import QualityGate
from .stages.s05_dedup_evaluator import DedupIndex, DedupEvaluator
from .stages.s06_dedup_committer import DedupCommitter
from .stages.s07_clustering import ActiveEventStore, EventClusterer
from .stages.s08_scoring import ScoringEngine
from .stages.s09_enrichment import EnrichmentStage
from .stages.s10_persistence import PersistenceStage
from .stages.s11_publication import PublicationStage

logger = logging.getLogger(__name__)


class IngestionStatus(str, Enum):
    SUCCESS = "success"
    DROPPED = "dropped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """
    Structured outcome of an observation passing through the canonical pipeline.
    """
    status: IngestionStatus
    event: Optional[TechEvent] = None
    article: Optional[NormalizedArticle] = None
    rejected_at_stage: Optional[str] = None
    abort_reason: Optional[str] = None
    correlation_id: str = ""
    stage_metrics: Dict[str, float] = field(default_factory=dict)
    total_latency_ms: float = 0.0

    @classmethod
    def success(
        cls,
        event: TechEvent,
        context: PipelineContext,
        article: Optional[NormalizedArticle] = None,
        total_latency_ms: float = 0.0,
    ) -> "IngestionResult":
        return cls(
            status=IngestionStatus.SUCCESS,
            event=event,
            article=article,
            correlation_id=context.correlation_id,
            stage_metrics=dict(context.stage_metrics),
            total_latency_ms=round(total_latency_ms, 3),
        )

    @classmethod
    def dropped(
        cls,
        stage_name: str,
        reason: Optional[str],
        context: PipelineContext,
        total_latency_ms: float = 0.0,
    ) -> "IngestionResult":
        return cls(
            status=IngestionStatus.DROPPED,
            rejected_at_stage=stage_name,
            abort_reason=reason,
            correlation_id=context.correlation_id,
            stage_metrics=dict(context.stage_metrics),
            total_latency_ms=round(total_latency_ms, 3),
        )

    @classmethod
    def error(
        cls,
        error_msg: str,
        context: Optional[PipelineContext] = None,
        total_latency_ms: float = 0.0,
    ) -> "IngestionResult":
        return cls(
            status=IngestionStatus.ERROR,
            abort_reason=error_msg,
            correlation_id=context.correlation_id if context else "",
            stage_metrics=dict(context.stage_metrics) if context else {},
            total_latency_ms=round(total_latency_ms, 3),
        )


def _unwrap_output(res: Any) -> Any:
    """Extract primary domain object from stage return value if wrapped in a tuple."""
    if res is None:
        return None
    if isinstance(res, tuple):
        return res[0]
    return res


class CanonicalPipelineRunner:
    """
    Canonical Sequential Pipeline Runner (Phase 3).
    """

    def __init__(
        self,
        bus: Optional[PublicationBus] = None,
        dedup_index: Optional[DedupIndex] = None,
        event_store: Optional[ActiveEventStore] = None,
        event_repository: Optional[EventRepositoryProtocol] = None,
        article_repository: Optional[ArticleRepositoryProtocol] = None,
        max_concurrency: int = 16,
    ):
        self.bus = bus if bus is not None else get_publication_bus()
        self.dedup_index = dedup_index if dedup_index is not None else DedupIndex()
        self.event_store = event_store if event_store is not None else ActiveEventStore()
        self.event_repository = event_repository
        self.article_repository = article_repository
        self.max_concurrency = max_concurrency

        # Initialize Stages S01–S11
        self.s01_normalizer = ObservationNormalizer()
        self.s02_freshness = FreshnessEvaluator()
        self.s03_relevance = TechRelevanceFilter()
        self.s04_quality = QualityGate()
        self.s05_dedup_eval = DedupEvaluator(index=self.dedup_index)
        self.s06_dedup_commit = DedupCommitter(index=self.dedup_index)
        self.s07_clustering = EventClusterer(store=self.event_store)
        self.s08_scoring = ScoringEngine()
        self.s09_enrichment = EnrichmentStage()
        self.s10_persistence = PersistenceStage(repository=self.event_repository)
        self.s11_publication = PublicationStage(bus=self.bus)

        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active_tasks: set[asyncio.Task] = set()
        self._running = True

    async def hydrate_cluster_store(self, window_hours: float = 48.0) -> int:
        """
        Explicit startup lifecycle operation to hydrate the active cluster store (S07)
        from the configured event repository.
        """
        if self.event_repository is None:
            logger.debug("No event_repository configured on runner; skipping hydration.")
            return 0
        return await self.s07_clustering.hydrate(self.event_repository, window_hours=window_hours)

    async def process_observation(
        self,
        observation: SourceObservation,
        dry_run: bool = False,
    ) -> IngestionResult:
        """
        Execute a SourceObservation through the canonical sequential pipeline.
        
        Args:
            observation: The incoming raw source observation domain model.
            dry_run: If True (shadow mode), executes S01–S08 only and skips S09–S11.
        """
        async with self._semaphore:
            start_total = time.perf_counter()
            context = PipelineContext(correlation_id=observation.id)

            # Extract correlation trace context if available
            parent_trace_ctx = None
            metrics_reg = None
            try:
                from src.observability.tracing import SpanContext, Tracer
                from src.observability.metrics import get_metrics_registry
                parent_trace_ctx = SpanContext.from_metadata(observation.metadata, operation_name="pipeline_execution")
                metrics_reg = get_metrics_registry()
            except Exception:
                pass

            try:
                # Helper for stage timing
                async def _timed_stage(stage_name: str, stage_obj, inp, bounded_reason: str):
                    t0 = time.perf_counter()
                    res = await stage_obj.process(inp, context)
                    dur = time.perf_counter() - t0
                    if metrics_reg:
                        metrics_reg.pipeline_stage_duration_seconds.observe(dur, stage=stage_name)
                    out = _unwrap_output(res)
                    if out is None or context.is_aborted:
                        if metrics_reg:
                            metrics_reg.pipeline_stage_failures_total.inc(stage=stage_name, reason=bounded_reason)
                    return out

                # -------------------------------------------------------------
                # S01: Normalization (SourceObservation -> NormalizedArticle)
                # -------------------------------------------------------------
                article = await _timed_stage("s01_normalizer", self.s01_normalizer, observation, "validation")
                if article is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s01_normalizer", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # S02: Freshness (Rejects STALE >72h)
                # -------------------------------------------------------------
                article = await _timed_stage("s02_freshness", self.s02_freshness, article, "validation")
                if article is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s02_freshness", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # S03: Tech Relevance (Rejects Non-Tech <0.40)
                # -------------------------------------------------------------
                article = await _timed_stage("s03_relevance", self.s03_relevance, article, "validation")
                if article is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s03_relevance", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # S04: Quality Gate (Evaluates Hygiene; Attaches QualityReport)
                # -------------------------------------------------------------
                article = await _timed_stage("s04_quality", self.s04_quality, article, "validation")
                if article is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s04_quality", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # S05: Dedup Evaluator (Read-Only; Attaches DedupDecision)
                # -------------------------------------------------------------
                article = await _timed_stage("s05_dedup_evaluator", self.s05_dedup_eval, article, "deduplication")
                if article is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s05_dedup_evaluator", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # S06: Dedup Committer (Quality Gated Mutation)
                # -------------------------------------------------------------
                article = await _timed_stage("s06_dedup_committer", self.s06_dedup_commit, article, "deduplication")
                if article is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s06_dedup_committer", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # Post-S06: Article Persistence (Persists Validated Canonical Article)
                # -------------------------------------------------------------
                if self.article_repository is not None and not dry_run:
                    await self.article_repository.save_article(article)
                    context.set("article_persisted", True)
                    if metrics_reg:
                        metrics_reg.pipeline_articles_persisted_total.inc()

                # -------------------------------------------------------------
                # S07: Event Clusterer (NormalizedArticle -> TechEvent)
                # -------------------------------------------------------------
                event = await _timed_stage("s07_clustering", self.s07_clustering, article, "clustering")
                if event is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s07_clustering", context.abort_reason, context, elapsed)

                # -------------------------------------------------------------
                # S08: Scoring Engine (TechEvent -> Scored TechEvent)
                # -------------------------------------------------------------
                event = await _timed_stage("s08_scoring", self.s08_scoring, event, "scoring")
                if event is None or context.is_aborted:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="dropped")
                    return IngestionResult.dropped("s08_scoring", context.abort_reason, context, elapsed)

                # Shadow Mode Dry-Run: Return before S09–S11
                if dry_run:
                    elapsed = (time.perf_counter() - start_total) * 1000.0
                    if metrics_reg:
                        metrics_reg.pipeline_runs_total.inc(status="success")
                    return IngestionResult.success(event, context, article, elapsed)

                # -------------------------------------------------------------
                # S09: Enrichment (Bounded Asynchronous Enrichment)
                # -------------------------------------------------------------
                event = await _timed_stage("s09_enrichment", self.s09_enrichment, event, "enrichment")

                # -------------------------------------------------------------
                # S10: Persistence (Persists TechEvent Aggregate)
                # -------------------------------------------------------------
                event = await _timed_stage("s10_persistence", self.s10_persistence, event, "persistence")
                if metrics_reg and event is not None:
                    metrics_reg.pipeline_events_updated_total.inc()

                # -------------------------------------------------------------
                # S11: Publication (Dispatches to Application PublicationBus)
                # -------------------------------------------------------------
                event = await _timed_stage("s11_publication", self.s11_publication, event, "publication")

                elapsed = (time.perf_counter() - start_total) * 1000.0
                if metrics_reg:
                    metrics_reg.pipeline_runs_total.inc(status="success")
                return IngestionResult.success(event, context, article, elapsed)

            except Exception as e:
                logger.error(
                    f"Unhandled error in CanonicalPipelineRunner processing '{observation.id}': {e}",
                    exc_info=True,
                )
                elapsed = (time.perf_counter() - start_total) * 1000.0
                if metrics_reg:
                    metrics_reg.pipeline_runs_total.inc(status="error")
                return IngestionResult.error(str(e), context, elapsed)

    async def drain(self, timeout: float = 5.0) -> None:
        """Allow active in-flight pipeline tasks to complete within timeout."""
        if not self._active_tasks:
            return
        logger.info(f"CanonicalPipelineRunner draining {len(self._active_tasks)} active tasks...")
        start = time.perf_counter()
        while self._active_tasks and (time.perf_counter() - start) < timeout:
            await asyncio.sleep(0.05)
        logger.info("CanonicalPipelineRunner drain completed.")

    def stop(self) -> None:
        self._running = False
