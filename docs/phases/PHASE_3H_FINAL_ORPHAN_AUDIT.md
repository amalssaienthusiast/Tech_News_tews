# Phase 3H Final Orphan & Architecture Audit

**Document Version**: 1.0.0  
**Status**: COMPLETE & RATIFIED  
**Author**: Principal System Architect & Google DeepMind Antigravity  
**Audit Scope**: Entire Repository Tree (`src/`, `tests/`, `gui_qt/`, root entrypoints)  
**Cumulative Test Status**: **174/174 PASSED** ✅  

---

## 1. Executive Summary

This final audit inventories every legacy, duplicate, and candidate orphan component across the entire repository following the completion of Phase 3 (Canonical Sequential Pipeline).

Every component has been verified against active execution paths, CLI entrypoints (`main_engine.py`, `telegram_feeder_bot.py`), API routes (`src/api/`), crawler swarm (`src/zombies/`), GUI desktop client (`gui_qt/`), and automated test suites.

---

## 2. Comprehensive Subsystem Classification Matrix

### 2.1 Pipeline Subsystem (`src/pipeline/`) — Canonical Layer

| Component / File | Symbol(s) | Status | Callers / Reachability | Tests | Replacement / Role |
|:---|:---|:---:|:---|:---|:---|
| `src/pipeline/protocols.py` | `PipelineStage`, `PipelineContext` | `ACTIVE_RUNTIME` | All stages S01–S11, `CanonicalPipelineRunner` | `test_pipeline_protocols.py` | Canonical stage protocol definition |
| `src/pipeline/adapters.py` | `SourceObservationAdapter` | `ACTIVE_RUNTIME` | `UnifiedFeedChainEngine._on_zombie_found_source` | `test_pipeline_protocols.py` | Zombie `EventSource` -> `SourceObservation` |
| `src/pipeline/runner.py` | `CanonicalPipelineRunner`, `IngestionResult` | `ACTIVE_RUNTIME` | `UnifiedFeedChainEngine.initialize()`, `main` | `test_canonical_pipeline_runner.py` | Central sequential pipeline orchestrator |
| `src/pipeline/stages/s01_normalizer.py` | `ObservationNormalizer` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_normalizer.py` | Stage 1 Normalization |
| `src/pipeline/stages/s02_freshness.py` | `FreshnessEvaluator` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_filters.py` | Stage 2 Temporal classification |
| `src/pipeline/stages/s03_relevance.py` | `TechRelevanceFilter` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_filters.py` | Stage 3 Domain relevance |
| `src/pipeline/stages/s04_quality.py` | `QualityGate` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_filters.py` | Stage 4 Text & structure quality |
| `src/pipeline/stages/s05_dedup_evaluator.py` | `DedupEvaluator`, `DedupIndex` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_dedup.py` | Stage 5 Read-only dedup evaluation |
| `src/pipeline/stages/s06_dedup_committer.py` | `DedupCommitter` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_dedup.py` | Stage 6 Quality-gated state commit |
| `src/pipeline/stages/s07_clustering.py` | `EventClusterer`, `ActiveEventStore` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_clustering.py` | Stage 7 Multi-source event clustering |
| `src/pipeline/stages/s08_scoring.py` | `ScoringEngine` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_stage_scoring.py` | Stage 8 Confidence, novelty, breaking scoring |
| `src/pipeline/stages/s09_enrichment.py` | `EnrichmentStage` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_canonical_pipeline_runner.py` | Stage 9 Bounded async enrichment |
| `src/pipeline/stages/s10_persistence.py` | `PersistenceStage` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_canonical_pipeline_runner.py` | Stage 10 Repository event persistence |
| `src/pipeline/stages/s11_publication.py` | `PublicationStage` | `ACTIVE_RUNTIME` | `CanonicalPipelineRunner` | `test_canonical_pipeline_runner.py` | Stage 11 Event publication bus dispatcher |

---

### 2.2 Engine Subsystem (`src/engine/`)

| File | Primary Symbol | Status | Current Callers | Target Phase | Reason Retained / Deferral Note |
|:---|:---|:---:|:---|:---:|:---|
| `src/engine/unified_chain.py` | `UnifiedFeedChainEngine` | `ACTIVE_RUNTIME` | `main_engine.py`, swarm callbacks | Phase 3 (Active) | Root container orchestrating Swarm + Canonical Runner |
| `src/engine/source_registry.py` | `SourceRegistry` | `ACTIVE_RUNTIME` | `UnifiedFeedChainEngine`, `ZombieSwarm` | Phase 3 (Active) | Central registry for tiered ingestion sources |
| `src/engine/publication_bus.py` | `PublicationBus` | `ACTIVE_RUNTIME` | `PublicationStage`, SSE routes, Telegram | Phase 2/3 (Active) | Asynchronous publication backbone |
| `src/engine/feed_chain.py` | `FeedChain` | `DEFERRED_TO_PHASE_6` | `main_engine.py`, `breaking_news_pipeline.py` | Phase 6 | Referenced in legacy CLI entrypoint |
| `src/engine/dedup_gate.py` | `DedupGate` | `DEFERRED_TO_PHASE_6` | `main_engine.py`, `breaking_news_pipeline.py` | Phase 6 | Referenced in legacy CLI entrypoint |
| `src/engine/quality_gate.py` | `QualityGate` | `DEFERRED_TO_PHASE_6` | `main_engine.py`, `breaking_news_pipeline.py` | Phase 6 | Referenced in legacy CLI entrypoint |
| `src/engine/breaking_news_pipeline.py` | `BreakingNewsScanner` | `DEFERRED_TO_PHASE_6` | `main_engine.py`, `orchestrator.py` | Phase 6 | Legacy breaking scanner CLI integration |
| `src/engine/cyclic_scheduler.py` | `CyclicSourceScheduler` | `DEFERRED_TO_PHASE_6` | `orchestrator.py` | Phase 6 | Legacy source polling scheduler |
| `src/engine/realtime_feeder.py` | `RealtimeNewsFeeder` | `DEFERRED_TO_PHASE_7` | `gui_qt/app_qt_migrated.py`, `orchestrator.py` | Phase 7 | `RobustDateParser` and feeder used in Qt GUI |
| `src/engine/enhanced_feeder.py` | `EnhancedNewsPipeline` | `DEFERRED_TO_PHASE_7` | `gui_qt/app_qt_migrated.py`, `main_engine.py` | Phase 7 | Legacy feeder wrapper used in Qt GUI |
| `src/engine/query_engine.py` | `QueryEngine` | `DEFERRED_TO_PHASE_6` | `src/engine/__init__.py`, `orchestrator.py` | Phase 6 | Query expansion and intent parsing |
| `src/engine/deep_scraper.py` | `DeepScraper` | `DEFERRED_TO_PHASE_4` | `src/engine/__init__.py`, `orchestrator.py` | Phase 4 | Deep content scraping logic |
| `src/engine/url_analyzer.py` | `URLAnalyzer` | `DEFERRED_TO_PHASE_4` | `src/engine/__init__.py`, `orchestrator.py` | Phase 4 | Content analysis helper |
| `src/engine/orchestrator.py` | `TechNewsOrchestrator`| `DEFERRED_TO_PHASE_6` | `src/engine/__init__.py`, `main_engine.py` | Phase 6 | Legacy coordination orchestrator |

---

### 2.3 Events Subsystem (`src/events/`)

| File | Symbol(s) | Status | Callers | Target Phase | Reason Retained / Deferral Note |
|:---|:---|:---:|:---|:---:|:---|
| `src/events/__init__.py` | `TechEvent`, `EventSource`, `EventStatus` | `COMPATIBILITY` | `src/zombies/`, `src/pipeline/adapters.py` | Phase 4 | Data models for event contracts |
| `src/events/event_types.py` | `EventSource`, `ZombieSpecies` | `DEFERRED_TO_PHASE_4` | `src/zombies/*.py`, `adapters.py` | Phase 4 | Active crawler emission contract |
| `src/events/event_store.py` | `EventStore` | `DEFERRED_TO_PHASE_5` | `src/api/routes/events.py` | Phase 5 | SQLite active event queries for REST endpoints |

---

### 2.4 Acquisition Subsystem (`src/zombies/`) — Deferred to Phase 4

| File | Symbol(s) | Status | Callers | Target Phase |
|:---|:---|:---:|:---|:---:|
| `src/zombies/swarm.py` | `ZombieSwarm` | `ACTIVE_RUNTIME` | `UnifiedFeedChainEngine` | Phase 4 (Refactor to emit `SourceObservation`) |
| `src/zombies/zombie_base.py` | `BaseZombie` | `ACTIVE_RUNTIME` | Zombie species implementations | Phase 4 |
| `src/zombies/z_rss.py` | `RssZombie` | `ACTIVE_RUNTIME` | `ZombieSwarm` | Phase 4 |
| `src/zombies/z_web.py` | `WebZombie` | `ACTIVE_RUNTIME` | `ZombieSwarm` | Phase 4 |
| `src/zombies/z_hacker.py` | `HackerNewsZombie`| `ACTIVE_RUNTIME` | `ZombieSwarm` | Phase 4 |
| `src/zombies/z_security.py` | `SecurityZombie` | `ACTIVE_RUNTIME` | `ZombieSwarm` | Phase 4 |
| `src/zombies/z_github.py` | `GitHubZombie` | `ACTIVE_RUNTIME` | `ZombieSwarm` | Phase 4 |
| `src/zombies/z_corp.py` | `CorporateZombie` | `ACTIVE_RUNTIME` | `ZombieSwarm` | Phase 4 |

---

### 2.5 API & Delivery Subsystems — Deferred to Phase 5 & Phase 6

| File | Primary Role | Status | Callers | Target Phase |
|:---|:---|:---:|:---|:---:|
| `src/api/routes/events.py` | `/v1/events` SSE & Query endpoints | `ACTIVE_RUNTIME` | Web clients, SSE consumers | Phase 5 |
| `src/api/routes/articles.py` | `/v1/articles` Query endpoints | `ACTIVE_RUNTIME` | Web clients | Phase 5 |
| `src/api/routes/search.py` | `/v1/search` Search endpoints | `ACTIVE_RUNTIME` | Web clients | Phase 5 |
| `src/api/routes/sentiment.py` | `/v1/sentiment` Endpoints | `ACTIVE_RUNTIME` | Web clients | Phase 5 |
| `telegram_feeder_bot.py` | Telegram Bot delivery subscriber | `ACTIVE_RUNTIME` | Telegram channels | Phase 6 |
| `main_engine.py` | Standalone CLI entrypoint | `DEFERRED_TO_PHASE_6` | CLI invocations | Phase 6 |
| `gui_qt/app_qt_migrated.py` | Desktop GUI client | `DEFERRED_TO_PHASE_7` | Desktop users | Phase 7 |

---

## 3. Audit Conclusion & Phase 3 Sign-Off

1. **Phase 3 Objective Achieved**: Canonical 11-stage sequential pipeline is fully built, tested, integrated, and active by default.
2. **Phase 3H Decommissioning Clean**: The 6 authorized pure-orphan legacy modules were deleted with zero broken imports and zero test failures.
3. **Downstream Roadmap Defined**:
   - **Phase 4**: Crawler Refactoring (Zombies directly emitting `SourceObservation`).
   - **Phase 5**: API Layer Refactoring (REST & SSE models mapped to canonical events).
   - **Phase 6**: CLI & Engine Modernization (`main_engine.py`, legacy gates retirement).
   - **Phase 7**: Desktop GUI Migration (`gui_qt` cleanup).
