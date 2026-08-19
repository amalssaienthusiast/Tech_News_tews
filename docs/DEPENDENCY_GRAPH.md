# Dependency Graph & Boundary Violation Analysis

**Document Status**: Phase 0 Baseline  
**Scope**: Inter-package dependencies, circular import cycles, layer inversion, and external third-party boundaries.

---

## 1. Architectural Layer Hierarchy (Target vs. Current)

### Target Layer Hierarchy (Strict Downward Flow)

```text
Layer 6: Delivery & UI          [api, telegram_feeder_bot, realtime, gui_qt, cli]
          ↓
Layer 5: Pipeline & Engine      [unified_chain, breaking_news_pipeline, feed_chain]
          ↓
Layer 4: Intelligence & Events  [event_clusterer, confidence_engine, freshness_gate, llm]
          ↓
Layer 3: Ingestion & Zombies    [zombies, swarm, bypass, normalizer]
          ↓
Layer 2: Storage & Persistence  [async_database, repository, ephemeral_store]
          ↓
Layer 1: Core Domain & Types    [core.types, exceptions, constants, utils]
```

---

## 2. Boundary Violations & Inverted Dependencies

Our static AST analysis revealed several critical layer boundary violations that compromise modularity:

| Violation | Source File | Target File | Impact & Problem | Remediation |
|:---|:---|:---|:---|:---|
| **API → Legacy DB** | `src/api/app.py` (L136) | `src/database.py` | Production FastAPI authentication relies on synchronous legacy `Database()` SQLite class. | Migrate `APIKeyManager` to `src/db_storage/async_database.py`. |
| **Engine → API (Cycle)** | `src/engine/unified_chain.py` (L108) | `src/api/routes/events.py` | Pipeline engine imports and invokes API broadcasting route (`broadcast_event_update`). | Engine should publish to an event bus / callback; API subscribes to bus. |
| **Events → Engine (Cycle)** | `src/events/event_clusterer.py` | `src/engine/source_registry.py` | Event clustering models import source descriptors from engine layer. | Move `SourceDescriptor` down into `src/core/types.py`. |
| **Bypass Sub-crate Cycles**| `src/bypass/` (multiple) | `src/bypass/` | 10+ circular import cycles between `content_platform_bypass`, `browser_engine`, `paywall`, and `anti_bot`. | Consolidate bypass utilities into clean single-responsibility modules with strict hierarchy. |
| **UI Isolation Leak** | `gui_qt/` | `src/database.py`, `src/scraper.py` | Desktop GUI directly initializes legacy scrapers and sync database connections. | GUI should communicate exclusively via API client or clean service interface. |

---

## 3. Circular Dependency Cycle Analysis

A complete AST graph traversal identified **155 cycle paths** across the codebase. The principal cycle clusters are:

### Cycle Cluster A: Bypass Escalation Ladder
```text
src.bypass.bypass_resolver
  → src.bypass.browser_engine
    → src.bypass.paywall
      → src.bypass.content_platform_bypass
        → src.bypass.browser_engine (CYCLE)
```

### Cycle Cluster B: Unified Chain & Event Brain
```text
src.engine.unified_chain
  → src.zombies.swarm
    → src.events.event_clusterer
      → src.api.routes.events (via lazy import)
        → src.engine.unified_chain (CYCLE)
```

### Cycle Cluster C: Database & Scraper Legacy Linkages
```text
src.database
  → src.scraper
    → src.feed_generator.live_feed
      → src.db_storage.db_handler
        → src.database (CYCLE)
```

---

## 4. Third-Party Library Boundaries & Constraints

| Dependency | Target Packages | Constraints & Notes |
|:---|:---|:---|
| `aiohttp` | `engine`, `zombies`, `api`, `realtime` | Core async networking. Must use shared connection pool; prohibit `ssl=False`. |
| `fastapi` / `uvicorn` | `api` | Modern async HTTP REST API gateway and WebSocket provider. |
| `aiosqlite` / `asyncpg` | `db_storage` | Non-blocking database drivers for SQLite and PostgreSQL. |
| `primp` | `bypass`, `crawler` | Fast Rust-based HTTP client with TLS and browser fingerprint impersonation. |
| `playwright` | `bypass.browser_engine` | Headless Chromium automation for complex CAPTCHA bypass. Must strictly close contexts. |
| `PyQt6` / `PySide6` | `gui_qt` | Desktop GUI toolkit. **Must never be imported in server/headless paths**. |
| `redis` / `celery` | `cache`, `queue` | Optional distributed caching and background job worker runtime. |
