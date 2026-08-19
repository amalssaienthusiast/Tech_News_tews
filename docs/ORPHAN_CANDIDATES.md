# Orphan Candidates & Dead Code Inventory

**Document Status**: Phase 0 Baseline  
**Deletion Policy**: Every deletion requires static and dynamic reference verification, proof of non-use, and passing test suites.

---

## 1. High-Confidence Deletion Candidates (Dead Code)

These files have been verified to have zero production references, are duplicate implementations, or are explicitly flagged as dead in project tooling:

| File Path | Lines | Reason / Evidence | Replacement / Canonical Module | Phase for Removal |
|:---|:---:|:---|:---|:---:|
| `src/database.py` | 110 | Legacy synchronous SQLite implementation. Explicitly flagged in `pyproject.toml` (`# legacy module; will be refactored separately`). | `src/db_storage/async_database.py` | Phase 8 |
| `src/scraper.py` | 915 | Legacy synchronous scraper module. Explicitly flagged in `pyproject.toml` (`# legacy module; production-dead per audit`). | `src/engine/deep_scraper.py` / `src/zombies/` | Phase 8 |
| `src/api/main.py` | 490 | Old duplicate FastAPI server. Docstring in `src/api/app.py` explicitly documents that its features were ported over. | `src/api/app.py` | Phase 8 |
| `api/` (root folder, 2 files) | 162 | `api/events.py` and `api/__init__.py` at root are an unreferenced duplicate copy of `src/api/routes/events.py`. | `src/api/routes/events.py` | Phase 8 |
| `src/ai_processor.py` | 240 | Legacy monolithic AI helper. Superseded by modular `src/intelligence/` package (`llm_client.py`, `llm_summarizer.py`). | `src/intelligence/llm_client.py` | Phase 8 |
| `src/bypass/tls_client.py` | 260 | Standalone custom TLS client. Superseded by `primp` client inside `bypass_resolver.py` Tier 1. | `src/bypass/bypass_resolver.py` | Phase 8 |
| `src/engine/cyclic_scheduler.py`| 310 | Legacy threading scheduler. Superseded by `ZombieSwarm` autonomous async lifecycle. | `src/zombies/swarm.py` | Phase 8 |
| `src/resilience/auto_fixer.py` | 410 | Over-engineered runtime monkey-patcher. Violates explicit failure semantics. | Standard exception handling & circuit breakers | Phase 8 |
| `src/resilience/warning_orchestrator.py` | 180 | Redundant logging wrapper. | Standard `logging` module | Phase 8 |

---

## 2. Merge & Consolidation Candidates

These modules contain functional logic that should be consolidated into canonical subsystems rather than deleted outright:

| Module | Lines | Target Subsystem | Consolidation Action |
|:---|:---:|:---|:---|
| `src/engine/breaking_news_pipeline.py` | 290 | `src/events/confidence_engine.py` | Merge breaking news detection heuristics into event confidence scoring. |
| `src/engine/enhanced_feeder.py` | 740 | `src/engine/unified_chain.py` | Merge necessary multi-source discovery into the canonical unified pipeline. |
| `src/db_storage/db_handler.py` | 185 | `src/db_storage/async_database.py` | Merge high-level CRUD helper methods into the async database repository layer. |
| `src/db_storage/unified_storage.py` | 410 | `src/db_storage/async_database.py` | Remove intermediate storage facade; direct callers to async repository. |
| `src/realtime/websocket_server.py` | 280 | `src/api/app.py` | Unify standalone websocket server into FastAPI `/feed/ws` endpoint. |
| `src/compatibility/rss_adapter.py` | 320 | `src/zombies/z_rss.py` | Merge legacy RSS parsing quirks into canonical RSS zombie. |

---

## 3. Verified Active Production Core (KEEP & PROTECT)

The following core modules are active, authoritative, and form the backbone of the production system:

- **Zombies**: `src/zombies/zombie_base.py`, `src/zombies/swarm.py`, `src/zombies/z_rss.py`, `src/zombies/z_github.py`, `src/zombies/z_hacker.py`, `src/zombies/z_security.py`, `src/zombies/z_web.py`
- **Engine**: `main_engine.py`, `src/engine/unified_chain.py`, `src/engine/source_registry.py`, `src/engine/dedup_gate.py`, `src/engine/quality_gate.py`, `src/engine/quality_filter.py`, `src/engine/content_enhancer.py`
- **Events**: `src/events/event_clusterer.py`, `src/events/confidence_engine.py`, `src/events/freshness_gate.py`, `src/events/event_types.py`, `src/events/entity_extractor.py`
- **Bypass**: `src/bypass/bypass_resolver.py`, `src/bypass/browser_engine.py`, `src/bypass/stealth.py`, `src/bypass/smart_proxy_router.py`, `src/bypass/paywall.py`
- **Storage**: `src/db_storage/async_database.py`, `src/db_storage/ephemeral_store.py`, `src/db_storage/migration.py`
- **API & Delivery**: `src/api/app.py`, `src/api/routes/*`, `telegram_feeder_bot.py`, `src/realtime/sse_broadcaster.py`
