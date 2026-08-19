# Phase 3H Component Audit: Legacy Runtime Components & Callers

**Document Version**: 1.0.0  
**Status**: APPROVED AUDIT SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  
**Target Subphase**: Subphase 3H (Safe Legacy Decommissioning & Production Cutover)

---

## 1. Executive Summary

This audit traces actual imports, runtime execution paths, test-suite dependencies, and compatibility bridges across all legacy components in `src/engine/` and `src/events/`.

Every component is formally classified under one of the 5 approved statuses:
- `ACTIVE_RUNTIME`: Actively invoked in standard operational flow.
- `TEST_ONLY`: Referenced only in legacy test files; not reachable in canonical runtime.
- `COMPATIBILITY`: Serves as a transitional bridge (e.g. `EventSource` in crawlers) until Phase 4.
- `DOCUMENTATION_ONLY`: Mentioned only in markdown documentation or comments.
- `ORPHAN`: Completely unreferenced across active runtime, tests, and APIs.
- `DELETE_AFTER_PHASE`: Scheduled for deletion in Phase 3H or downstream phases.

---

## 2. In-Depth Component Classification & Dependency Traces

### 2.1 Engine Legacy Pipeline Components (`src/engine/`)

| File / Component | Direct Callers / Importers | Classification | Runtime Replacement | Decommission Risk |
|:---|:---|:---:|:---|:---:|
| `src/engine/feed_chain.py` (`FeedChain`) | `src/engine/unified_chain.py`, `src/engine/breaking_news_pipeline.py`, `src/engine/cyclic_scheduler.py` | `DELETE_AFTER_PHASE` (3H-C) | `CanonicalPipelineRunner` + `PublicationBus` | Low |
| `src/engine/dedup_gate.py` (`DedupGate`) | `src/engine/unified_chain.py`, `src/engine/cyclic_scheduler.py` | `DELETE_AFTER_PHASE` (3H-C) | Stage 5 `DedupEvaluator` + Stage 6 `DedupCommitter` | Low |
| `src/engine/quality_gate.py` (`QualityGate`) | `src/engine/unified_chain.py`, `src/engine/cyclic_scheduler.py` | `DELETE_AFTER_PHASE` (3H-C) | Stage 4 `QualityGate` (`src/pipeline/stages/s04_quality.py`) | Low |
| `src/engine/content_enhancer.py` (`ContentEnhancer`) | `src/engine/unified_chain.py` | `DELETE_AFTER_PHASE` (3H-C) | Stage 9 `EnrichmentStage` (`src/pipeline/stages/s09_enrichment.py`) | Low |
| `src/engine/breaking_news_pipeline.py` | `src/engine/orchestrator.py` | `DELETE_AFTER_PHASE` (3H-C) | `ScoringEngine` (`TechEvent.is_breaking`) + `PublicationStage` (HIGH priority) | Low |
| `src/engine/cyclic_scheduler.py` | `src/engine/orchestrator.py` | `DELETE_AFTER_PHASE` (3H-C) | `ZombieSwarm` crawler acquisition | Medium |
| `src/engine/realtime_feeder.py` | `src/engine/orchestrator.py` | `DELETE_AFTER_PHASE` (3H-C) | `ZombieSwarm` | Low |
| `src/engine/enhanced_feeder.py` | `src/engine/orchestrator.py` | `DELETE_AFTER_PHASE` (3H-C) | `ZombieSwarm` | Low |

### 2.2 Legacy Event Brain Components (`src/events/`)

| File / Component | Direct Callers / Importers | Classification | Runtime Replacement | Decommission Risk |
|:---|:---|:---:|:---|:---:|
| `src/events/event_clusterer.py` (`EventClusterer`) | `src/engine/unified_chain.py` (legacy path) | `DELETE_AFTER_PHASE` (3H-C) | Stage 7 `EventClusterer` (`src/pipeline/stages/s07_clustering.py`) | Low |
| `src/events/confidence_engine.py` (`ConfidenceEngine`) | `src/engine/unified_chain.py` (legacy path) | `DELETE_AFTER_PHASE` (3H-C) | Stage 8 `ScoringEngine` (`src/pipeline/stages/s08_scoring.py`) | Low |
| `src/events/freshness_gate.py` (`FreshnessGate`) | `src/engine/unified_chain.py` (legacy path) | `DELETE_AFTER_PHASE` (3H-C) | Stage 2 `FreshnessEvaluator` + Stage 8 Freshness scoring | Low |
| `src/events/timeline_builder.py` | `src/events/event_clusterer.py` | `ORPHAN` | Stage 7 `TimelineEntry` integration in `TechEvent` | Very Low |
| `src/events/entity_extractor.py` | `src/events/event_clusterer.py` | `ORPHAN` | Stage 7 Entity matching in `ActiveEventStore` | Very Low |
| `src/events/event_store.py` (`EventStore`) | `src/api/routes/events.py` | `COMPATIBILITY` (Retain for Phase 5 API migration) | Stage 10 `PersistenceStage` | Medium |
| `src/events/event_types.py` (`EventSource`) | `src/zombies/*.py`, `src/pipeline/adapters.py` | `COMPATIBILITY` (Retain until Phase 4 Zombie refactor) | `SourceObservation` | Medium |

---

## 3. Findings & Safety Boundaries

1. **Crawler Acquisition Invariant**: `EventSource` in `src/events/event_types.py` is currently imported by active zombies (`z_rss`, `z_web`, `z_hacker`, `z_security`, `z_github`, `z_corp`, `swarm.py`). It must be retained as a `COMPATIBILITY` contract until Phase 4 replaces raw zombie emissions with direct `SourceObservation`.
2. **API Query Invariant**: `EventStore` in `src/events/event_store.py` is imported by `src/api/routes/events.py` for read queries (`/v1/events`). It must remain in place until Phase 5 updates API read models.
3. **Legacy Execution Paths**: In `src/engine/unified_chain.py`, `_run_legacy_pipeline()` and legacy gating instances (`self.feed`, `self.dedup`, `self.quality`, `self.enhancer`, `self._event_clusterer`, `self._confidence_engine`, `self._freshness_gate`) can be retired in controlled batches.
