# Architecture Inventory & Module Classification

> [!NOTE]
> **HISTORICAL DOCUMENT / SUPERSEDED ARCHITECTURE INVENTORY**
> This document represents the legacy Phase 0 architectural inventory and module classification.
> For the current authoritative, frozen production runtime architecture (Phase 8+), refer to [`docs/CANONICAL_RUNTIME.md`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/docs/CANONICAL_RUNTIME.md).

**Document Status**: 🟡 Historical (Phase 0 Baseline — Preserved for Audit Trail)
**Classification Standards**: `KEEP` | `REFACTOR` | `MERGE` | `REPLACE` | `DEPRECATE` | `DELETE`

---

## 1. Domain-by-Domain Architecture Classification

### 1.1 Ingestion & Collectors (`src/zombies/`, `src/sources/`, `src/scrapers/`, `src/crawler/`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/zombies/zombie_base.py` | 131 | `REFACTOR` | **KEEP as foundation**. Clean lifecycle, jitter, and hunger scoring. Needs rate-limit state machine, structured logging, and source-health state transitions. |
| `src/zombies/swarm.py` | 135 | `REFACTOR` | **KEEP**. Manages multi-species zombie lifecycle. Refactor to support dynamic resource allocation based on source yield. |
| `src/zombies/z_github.py` | 238 | `REFACTOR` | **KEEP**. Fix P1 rate-limiting bug: parse `X-RateLimit-Reset` and `Retry-After`, enter cooldown, prevent 403 hammering. Fix deprecated `get_event_loop()`. |
| `src/zombies/z_rss.py` | 120 | `KEEP` | Solid RSS discovery zombie. Standardize exception handling and ETags. |
| `src/zombies/z_hacker.py` | 170 | `KEEP` | Hacker News API collector. Working reliably. |
| `src/zombies/z_security.py` | 35 | `KEEP` | NVD / CVE security advisories collector. |
| `src/zombies/z_web.py` | 115 | `REFACTOR` | Generic HTML scraper zombie. Integrate with consolidated bypass client. |
| `src/zombies/z_corp.py` | 28 | `MERGE` | Merge into `z_rss.py` / `z_web.py` as a configuration profile. |
| `src/sources/` (11 files) | 4,089 | `MERGE` | Legacy source adapters (Google News, Bing, Reddit, Twitter, TechCrunch). Merge canonical source extractors into clean Zombie species. |
| `src/scrapers/` (6 files) | 358 | `DEPRECATE` | Legacy scraper factory (`ScraperFactory`, `BaseScraper`). Already flagged as legacy in `pyproject.toml`. Migrate remaining calls to Zombie adapters and delete. |
| `src/scraper.py` | 915 | `DELETE` | Root-level legacy scraper. Marked as dead code in `pyproject.toml`. Consumers have migrated to `src/engine/deep_scraper.py` and zombies. |
| `src/crawler/` (4 files) | 1,405 | `REFACTOR` | Deep web crawler (`primp_crawler.py`, `crawler_manager.py`). Restrict to on-demand deep extraction; isolate from canonical ingestion path. |

---

### 1.2 Pipeline & Orchestration (`src/engine/`, `src/events/`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/engine/unified_chain.py` | 180 | `REFACTOR` | **CRITICAL P1 FIX**. Eliminate dual-generation routing in `_on_zombie_found_source()`. Route strictly: `Zombie -> SourceObservation -> Normalizer -> Freshness -> Relevance -> Quality -> Dedup -> EventClusterer -> Enrichment -> Persistence -> Publication`. |
| `src/engine/dedup_gate.py` | 191 | `REFACTOR` | **CRITICAL P1 FIX**. Fix dedup ordering (distinguish SEEN vs QUALIFIED vs ACCEPTED). Eliminate synchronous `sqlite3.connect()` blocking asyncio loop. Implement bounded in-memory cache and scalable LSH lookup. |
| `src/engine/quality_gate.py` | 106 | `KEEP` | Clean quality check wrapper (`check()`, `check_strict()`, `check_standard()`). Maintain as the canonical quality validation gate. |
| `src/engine/quality_filter.py` | 1,320 | `REFACTOR` | Rich rule-based spam/relevance filter. Refactor to return explainable `QualityReport` with score, matched terms, and rejection reason codes instead of simple booleans. |
| `src/engine/source_registry.py` | 320 | `KEEP` | Authoritative registry for active feed sources, descriptors, and tier weights. |
| `src/engine/breaking_news_pipeline.py` | 290 | `MERGE` | Merge breaking news detection logic into canonical Event Brain confidence / importance scoring stage. |
| `src/engine/enhanced_feeder.py` | 740 | `DEPRECATE` | Legacy enhanced pipeline wrapper that duplicates discovery and bypass calls. Merge necessary discovery logic into canonical pipeline; deprecate file. |
| `src/engine/cyclic_scheduler.py` | 310 | `DELETE` | Legacy round-robin thread scheduler. Replaced by `ZombieSwarm` async lifecycle. |
| `src/engine/feed_chain.py` | 85 | `REFACTOR` | Callback subscriber bus for published articles. Streamline into lightweight publication bus. |
| `src/engine/content_enhancer.py` | 120 | `REFACTOR` | Asynchronous article content enrichment. Isolate behind bounded queue and circuit breaker so slow enrichment never blocks ingestion. |
| `src/engine/rejected_metadata_store.py` | 185 | `REFACTOR` | Stores rejected article metadata for diagnostics. Convert synchronous SQLite operations to non-blocking storage. |
| `src/events/event_clusterer.py` | 519 | `REFACTOR` | Fix P2 bugs: correct bigram ordering bug (ordered tokens -> bigrams -> set), enforce true `MAX_ACTIVE_EVENTS` hard bound, rename lexical matching accurately or add real optional embeddings. |
| `src/events/confidence_engine.py` | 165 | `KEEP` | Multi-source confirmation, official source weighting, tier weighting. |
| `src/events/freshness_gate.py` | 145 | `REFACTOR` | Implement first-class freshness classification (`F0` ≤5m, `F1` ≤15m, `F2` ≤30m, `F3` ≤60m, `F4` ≤6h, `F5` ≤24h, `STALE`, `UNKNOWN`). Explicit UNKNOWN policy. |
| `src/events/event_types.py` | 260 | `KEEP` | `TechEvent`, `EventSource`, `TimelineEntry`, `EventStatus`, `FreshnessLevel`. Foundation for Event Brain. |
| `src/events/entity_extractor.py` | 340 | `KEEP` | Fast rule-based tech entity & topic extractor. |

---

### 1.3 Bypass & Web Acquisition (`src/bypass/`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/bypass/bypass_resolver.py` | 200 | `REFACTOR` | Core 5-tier escalation resolver. Fix P0 `ssl=False` security bug. Annotate provenance (`retrieval_method`, `archive_timestamp`). Reuse long-lived `aiohttp.ClientSession`. |
| `src/bypass/anti_bot.py` | 420 | `MERGE` | Challenge and CAPTCHA detection routines. Merge with `bypass_resolver.py`. |
| `src/bypass/stealth.py` | 380 | `KEEP` | Browser user-agent headers, fingerprint randomization. |
| `src/bypass/browser_engine.py` | 450 | `KEEP` | Playwright stealth automation (Tier 2/3). Ensure headless execution and strict browser context cleanup to prevent memory leaks. |
| `src/bypass/smart_proxy_router.py` | 290 | `KEEP` | Proxy rotation for Tier 3 escalation. |
| `src/bypass/paywall.py` | 310 | `REFACTOR` | Archive and paywall bypass (Tier 4). Ensure output preserves archive provenance metadata. |
| `src/bypass/tls_client.py` | 260 | `DELETE` | Duplicate TLS wrapper; superseded by `primp` TLS client in Tier 1. |

---

### 1.4 Persistence & Database (`src/db_storage/`, `src/database.py`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/db_storage/async_database.py` | 920 | `KEEP` | **Primary Authoritative Async Database**. Native `aiosqlite` and `asyncpg` (PostgreSQL) engine with connection pooling and schema management. |
| `src/db_storage/db_handler.py` | 185 | `MERGE` | High-level data accessor. Merge directly into clean repository pattern on top of `async_database.py`. |
| `src/db_storage/unified_storage.py` | 410 | `REPLACE` | Confusing intermediate storage facade with overlapping responsibilities. Replace with unified `Repository` abstraction. |
| `src/db_storage/ephemeral_store.py` | 340 | `KEEP` | Redis / in-memory cache for fast-changing operational state. |
| `src/db_storage/migration.py` | 430 | `KEEP` | SQLite to PostgreSQL data migration tooling. |
| `src/database.py` | 110 | `DELETE` | Root-level synchronous legacy SQLite module. Marked as dead code in `pyproject.toml`. Migrate `APIKeyManager` to `async_database.py` and delete `database.py`. |

---

### 1.5 API & Delivery Surfaces (`src/api/`, `main_engine.py`, `telegram_feeder_bot.py`, `src/realtime/`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/api/app.py` | 506 | `REFACTOR` | Production FastAPI application. Fix missing `import asyncio` in websocket route. Unify security model with engine API. Standardize OpenAPI documentation. |
| `src/api/main.py` | 490 | `DELETE` | Old duplicate API server. Its features were ported into `app.py`. Verified dead code. |
| `src/api/routes/` (4 files) | 480 | `KEEP` | Modular API route handlers (`events.py`, `articles.py`, `search.py`, `sentiment.py`). |
| `api/` (root folder, 2 files) | 162 | `DELETE` | Root-level duplicate API folder. Unused copy of event endpoints. |
| `main_engine.py` | 654 | `REFACTOR` | Central engine server. Fix P0 security bugs: remove wildcard CORS (`*`), add API key verification to data endpoints, bind to configurable host. |
| `telegram_feeder_bot.py` | 980 | `REFACTOR` | High-performance Telegram delivery bot. Remove hardcoded fallback credentials, enforce environment variable loading, add duplicate dispatch prevention. |
| `src/realtime/websocket_server.py`| 280 | `MERGE` | Merge websocket server functionality directly into `src/api/app.py` `/feed/ws`. |
| `src/realtime/sse_broadcaster.py` | 180 | `KEEP` | Reusable Server-Sent Events broadcasting component. |

---

### 1.6 Intelligence & AI (`src/intelligence/`, `src/ai_processor.py`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/intelligence/llm_client.py` | 380 | `KEEP` | Provider abstraction for Gemini, OpenAI, Anthropic, Local LLMs. |
| `src/intelligence/llm_summarizer.py`| 310 | `KEEP` | Structured article summarization and key takeaways generation. |
| `src/intelligence/relevance_classifier.py`| 420 | `REFACTOR` | Multi-dimensional technology domain scoring (AI, Cloud, Security, Hardware, etc.). Make scores explainable. |
| `src/ai_processor.py` | 240 | `DELETE` | Legacy monolithic AI script. Superseded by modular `src/intelligence/` package. |

---

### 1.7 Compatibility & Resilience (`src/compatibility/`, `src/resilience/`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `src/compatibility/package_shim.py`| 310 | `DEPRECATE` | Dynamic package import shim. Migrate legacy callers and schedule for removal in Phase 8. |
| `src/compatibility/rss_adapter.py` | 320 | `MERGE` | Legacy RSS format adapter. Merge logic into `src/zombies/z_rss.py`. |
| `src/resilience/source_health.py` | 210 | `KEEP` | Source health state tracker. Expand to track full health state machine (`HEALTHY`, `DEGRADED`, `RATE_LIMITED`, `COOLDOWN`, `RECOVERING`). |
| `src/resilience/deprecation_manager.py`| 160 | `KEEP` | Runtime deprecation warning and logging utility. |
| `src/resilience/auto_fixer.py` | 410 | `DELETE` | Over-engineered auto-repair monkey-patcher. Violates explicit failure and no-silent-fallback engineering principles. |
| `src/resilience/warning_orchestrator.py`| 180 | `DELETE` | Wrapper around warning logs. Unnecessary layer. |

---

### 1.8 Desktop GUI (`gui_qt/`, `run_qt.py`)

| Module / Package | Lines | Verdict | Rationale & Migration Strategy |
|:---|:---:|:---:|:---|
| `gui_qt/` (53 files) | 23,278 | `ISOLATE` | Desktop PyQt6 GUI client. **Do not import inside headless engine/server paths**. Verify zero server-side imports from `gui_qt`. |
| `run_qt.py` | 30 | `KEEP` | Independent launcher script for GUI desktop client. |
