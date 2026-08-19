# Phase 3H Deletion Matrix: Module-by-Module Authorization

**Document Version**: 1.0.0  
**Status**: APPROVED DELETION SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Authoritative Deletion Matrix

| File / Module | Current Callers | Runtime Status | Replacement Module | Migration Proof Required | Risk Level | Authorization Status |
|:---|:---|:---:|:---|:---|:---:|:---:|
| `src/events/event_clusterer.py` | None in active runtime | ORPHAN | `src/pipeline/stages/s07_clustering.py` | Multi-source clustering tests green | Very Low | **DELETE IN 3H-C** |
| `src/events/confidence_engine.py` | None in active runtime | ORPHAN | `src/pipeline/stages/s08_scoring.py` | Scoring engine tests green | Very Low | **DELETE IN 3H-C** |
| `src/events/freshness_gate.py` | None in active runtime | ORPHAN | `src/pipeline/stages/s02_freshness.py` | Freshness evaluator tests green | Very Low | **DELETE IN 3H-C** |
| `src/events/timeline_builder.py` | None in active runtime | ORPHAN | `TechEvent.add_timeline_entry()` | Timeline ordering tests green | Very Low | **DELETE IN 3H-C** |
| `src/events/entity_extractor.py` | None in active runtime | ORPHAN | `ActiveEventStore` entity matching | Entity matching tests green | Very Low | **DELETE IN 3H-C** |
| `src/engine/content_enhancer.py` | None in active runtime | ORPHAN | `src/pipeline/stages/s09_enrichment.py` | Bounded enrichment test green | Very Low | **DELETE IN 3H-C** |
| `src/events/event_types.py` | `src/zombies/*.py`, `src/pipeline/adapters.py` | COMPATIBILITY | `SourceObservation` | **RETAINED** until Phase 4 (Crawler Refactoring) | Medium | **RETAIN FOR LATER PHASE (Phase 4)** |
| `src/events/event_store.py` | `src/api/routes/events.py` | COMPATIBILITY | `PersistenceStage` | **RETAINED** until Phase 5 (API Refactoring) | Medium | **RETAIN FOR LATER PHASE (Phase 5)** |
| `src/engine/feed_chain.py` | `main_engine.py`, `breaking_news_pipeline.py` | COMPATIBILITY | `CanonicalPipelineRunner` + `PublicationBus` | Main engine refactor complete | Medium | **RETAIN FOR LATER PHASE (Phase 6)** |
| `src/engine/dedup_gate.py` | `main_engine.py`, `breaking_news_pipeline.py` | COMPATIBILITY | `s05_dedup_evaluator.py`, `s06_dedup_committer.py` | Main engine refactor complete | Medium | **RETAIN FOR LATER PHASE (Phase 6)** |
| `src/engine/quality_gate.py` | `main_engine.py`, `breaking_news_pipeline.py` | COMPATIBILITY | `src/pipeline/stages/s04_quality.py` | Main engine refactor complete | Medium | **RETAIN FOR LATER PHASE (Phase 6)** |
| `src/engine/breaking_news_pipeline.py` | `main_engine.py`, `orchestrator.py` | COMPATIBILITY | `s08_scoring.py` + `s11_publication.py` | Main engine refactor complete | Medium | **RETAIN FOR LATER PHASE (Phase 6)** |
| `src/engine/cyclic_scheduler.py` | `orchestrator.py` | COMPATIBILITY | `ZombieSwarm` | Orchestrator refactor complete | Medium | **RETAIN FOR LATER PHASE (Phase 6)** |
| `src/engine/realtime_feeder.py` | `gui_qt/app_qt_migrated.py`, `orchestrator.py` | COMPATIBILITY | `ZombieSwarm` | GUI Qt refactor complete | High | **RETAIN FOR LATER PHASE (Phase 7)** |
| `src/engine/enhanced_feeder.py` | `gui_qt/app_qt_migrated.py`, `main_engine.py` | COMPATIBILITY | `CanonicalPipelineRunner` | GUI Qt refactor complete | High | **RETAIN FOR LATER PHASE (Phase 7)** |

---

## 2. Invariant Checklist Before Deletion

- [x] Canonical pipeline default is verified active and passing.
- [x] Callers in `src/engine/unified_chain.py` removed before physical file deletion.
- [x] Zero references remain in active code paths.
- [x] Retained files (`event_types.py`, `event_store.py`) explicitly protected.
