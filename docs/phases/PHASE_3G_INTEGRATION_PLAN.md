# Phase 3G Integration Plan: Runtime Ingestion & Pipeline Wiring

**Document Version**: 1.0.0  
**Status**: APPROVED DESIGN SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Objectives

1. Wire `CanonicalPipelineRunner` into `UnifiedFeedChainEngine` (`src/engine/unified_chain.py`).
2. Implement Stages S09 (Enrichment), S10 (Persistence), S11 (Publication), and `CanonicalPipelineRunner` in `src/pipeline/`.
3. Provide feature flag `ENABLE_CANONICAL_PIPELINE` and multi-mode operation (`active`, `shadow`, `legacy`).
4. Ensure **Zero Duplicate Publication**: canonical and legacy pipelines will never dual-publish the same story.

---

## 2. Allowed File Changes

### 2.1 New Files in `src/pipeline/`:
- `src/pipeline/runner.py`: The `CanonicalPipelineRunner` executing S01–S11.
- `src/pipeline/stages/s09_enrichment.py`: Lightweight, timeout-bounded enrichment stage.
- `src/pipeline/stages/s10_persistence.py`: Event persistence stage.
- `src/pipeline/stages/s11_publication.py`: Publication stage publishing to `PublicationBus`.
- `tests/test_canonical_pipeline_runner.py`: End-to-end unit and integration tests.

### 2.2 Modified Files:
- `src/pipeline/stages/__init__.py`: Export S09, S10, S11.
- `src/pipeline/__init__.py`: Export `CanonicalPipelineRunner`.
- `src/engine/unified_chain.py`: Wire `CanonicalPipelineRunner` under feature flag.

### 2.3 Forbidden Files:
- Zero modifications to legacy classes: `FeedChain`, `DedupGate`, `QualityGate`, `ContentEnhancer`, `src/events/event_clusterer.py`, `src/zombies/`, `src/api/`.

---

## 3. Detailed Wiring in `UnifiedFeedChainEngine`

### 3.1 Initialization Sequence
```python
# In UnifiedFeedChainEngine.initialize():
from ..pipeline.runner import CanonicalPipelineRunner
from ..pipeline.adapters import SourceObservationAdapter

# Instantiate canonical runner with application publication bus
self.canonical_runner = CanonicalPipelineRunner(bus=self.bus)
```

### 3.2 Ingestion Callback Routing (`_on_zombie_found_source`)
```python
async def _on_zombie_found_source(self, source: "EventSource") -> None:
    mode = os.environ.get("CANONICAL_PIPELINE_MODE", "active" if ENABLE_CANONICAL_PIPELINE else "legacy")

    if mode == "active":
        # 100% Canonical Ingestion
        obs = SourceObservationAdapter.from_event_source(source)
        await self.canonical_runner.process_observation(obs)
    elif mode == "shadow":
        # Dual-run: Legacy publishes; Canonical runs with publication disabled
        obs = SourceObservationAdapter.from_event_source(source)
        asyncio.create_task(self.canonical_runner.process_observation(obs, dry_run=True))
        await self._run_legacy_ingestion(source)
    else:
        # Legacy Ingestion
        await self._run_legacy_ingestion(source)
```

---

## 4. Execution-Scoped Flow & Dropped Item Handling

```python
async def process_observation(self, observation: SourceObservation, dry_run: bool = False) -> IngestionResult:
    context = PipelineContext(correlation_id=observation.id)
    
    try:
        # S01: Normalization
        article = await self.s01_normalizer.process(observation, context)
        if article is None or context.is_aborted:
            return IngestionResult.dropped("s01_normalizer", context.abort_reason)

        # S02: Freshness
        freshness_res = await self.s02_freshness.process(article, context)
        if freshness_res is None or context.is_aborted:
            return IngestionResult.dropped("s02_freshness", context.abort_reason)
        article = freshness_res[0]

        # S03: Relevance
        relevance_res = await self.s03_relevance.process(article, context)
        if relevance_res is None or context.is_aborted:
            return IngestionResult.dropped("s03_relevance", context.abort_reason)
        article = relevance_res[0]

        # S04: Quality Gate
        quality_res = await self.s04_quality.process(article, context)
        if quality_res is None or context.is_aborted:
            return IngestionResult.dropped("s04_quality", context.abort_reason)
        article = quality_res[0]

        # S05: Dedup Evaluator (Read-Only)
        dedup_res = await self.s05_dedup_eval.process(article, context)
        if dedup_res is None or context.is_aborted:
            return IngestionResult.dropped("s05_dedup_evaluator", context.abort_reason)
        article = dedup_res[0]

        # S06: Dedup Committer (Quality Gated)
        commit_res = await self.s06_dedup_commit.process(article, context)
        if commit_res is None or context.is_aborted:
            return IngestionResult.dropped("s06_dedup_committer", context.abort_reason)

        # S07: Event Clusterer
        event = await self.s07_clustering.process(article, context)
        if event is None or context.is_aborted:
            return IngestionResult.dropped("s07_clustering", context.abort_reason)

        # S08: Scoring Engine
        event = await self.s08_scoring.process(event, context)
        if event is None or context.is_aborted:
            return IngestionResult.dropped("s08_scoring", context.abort_reason)

        # S09: Enrichment (Non-Blocking)
        event = await self.s09_enrichment.process(event, context)

        # S10: Persistence
        event = await self.s10_persistence.process(event, context)

        # S11: Publication
        if not dry_run:
            await self.s11_publication.process(event, context)

        return IngestionResult.success(event)

    except Exception as e:
        logger.error(f"Unhandled pipeline error on {observation.id}: {e}", exc_info=True)
        return IngestionResult.error(str(e))
```
