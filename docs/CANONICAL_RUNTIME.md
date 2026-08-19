# Canonical Production Runtime Specification

**Authoritative Architecture Document**  
**Phase**: Phase 8 Engineering Hardening — Gate 8E-H1  
**Status**: 🟢 FROZEN & AUTHORITATIVE  
**Date**: `2026-08-17`  

---

## 1. Authoritative Production Runtime Overview

The Tech News Scrapper repository has undergone multi-phase evolution (Phase 1 through Phase 8). To eliminate architectural dual-generation ambiguity, this document establishes the **ONE authoritative production runtime architecture**.

```text
                               ┌────────────────────────────────────────┐
                               │           SOURCE FLEET REGISTRY        │
                               │        (src/engine/source_registry)     │
                               └───────────────────┬────────────────────┘
                                                   │
                                                   ▼
                               ┌────────────────────────────────────────┐
                               │       ACQUISITION & ZOMBIE SWARM       │
                               │           (src/zombies/swarm)          │
                               │  RSS | Reddit | HTTP | Playwright / WG │
                               └───────────────────┬────────────────────┘
                                                   │
                                                   ▼
                               ┌────────────────────────────────────────┐
                               │     INGESTION QUEUE & COORDINATOR      │
                               │       (src/queue/priority_queue)       │
                               │        (src/zombies/coordinator)      │
                               └───────────────────┬────────────────────┘
                                                   │
                                                   ▼
                               ┌────────────────────────────────────────┐
                               │       CANONICAL S01–S11 PIPELINE       │
                               │          (src/pipeline/runner)         │
                               │ S01 Validate  S05 Classify  S09 Enrich │
                               │ S02 CanonURL  S06 Detect    S10 Persist│
                               │ S03 DedupGate S07 Intel     S11 Publish│
                               │ S04 Extract   S08 Priority             │
                               └───────────────────┬────────────────────┘
                                                   │
                         ┌─────────────────────────┴─────────────────────────┐
                         ▼                                                   ▼
       ┌───────────────────────────────────┐               ┌───────────────────────────────────┐
       │      CANONICAL PERSISTENCE        │               │       REAL-TIME EVENT BUS         │
       │       (src/storage/sqlite_*)      │               │     (src/engine/publication_bus)  │
       │  SqliteEngine (WAL, NORMAL sync)  │               │   PublicationBus (async fanout)   │
       │  SqliteArticleRepository (FTS5)   │               └─────────────────┬─────────────────┘
       │  SqliteEventRepository            │                                 │
       └─────────────────┬─────────────────┘                                 │
                         │                                                   │
                         └─────────────────────────┬─────────────────────────┘
                                                   │
                                                   ▼
                               ┌────────────────────────────────────────┐
                               │        CANONICAL PRODUCTION API        │
                               │           (src/api/app:app)            │
                               │  FastAPI (ASGI) | OpenAPI / Swagger    │
                               │  Prometheus Metrics (/metrics)         │
                               │  Liveness / Readiness (/health)        │
                               │  RBAC Auth (X-API-Key: ADMIN/RW/RO)    │
                               │  Search & Article Endpoints            │
                               └────────────────────────────────────────┘
```

---

## 2. Component Ownership Matrix

| Responsibility Domain | Authoritative Owner Component | Module Path | Status |
|---|---|---|---|
| **Source Fleet Definition** | `SourceRegistry` | [`src/engine/source_registry.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/source_registry.py) | 🟢 Canonical |
| **Acquisition & Fetching** | `ZombieSwarm` & `BypassResolver` | [`src/zombies/swarm.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/swarm.py), [`src/bypass/`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/) | 🟢 Canonical |
| **Dynamic Source Discovery** | `DiscoveryLifecycleManager` | [`src/discovery/lifecycle.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/discovery/lifecycle.py) | 🟢 Canonical |
| **Ingestion Priority Queue** | `StarvationSafeIngestionQueue` | [`src/queue/priority_queue.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/queue/priority_queue.py) | 🟢 Canonical |
| **Multi-Process Coordination**| `SqliteSwarmCoordinator` | [`src/zombies/coordinator.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/coordinator.py) | 🟢 Canonical |
| **Canonical Pipeline (S01-S11)**| `CanonicalPipelineRunner` | [`src/pipeline/runner.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/pipeline/runner.py), [`src/pipeline/stages/`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/pipeline/stages/) | 🟢 Canonical |
| **Persistence Engine & WAL** | `SqliteEngine` | [`src/storage/sqlite_engine.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_engine.py) | 🟢 Canonical |
| **Article Storage & FTS5** | `SqliteArticleRepository` | [`src/storage/sqlite_article_repository.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_article_repository.py) | 🟢 Canonical |
| **Event Storage & Graphs** | `SqliteEventRepository` | [`src/storage/sqlite_event_repository.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_event_repository.py) | 🟢 Canonical |
| **Realtime Event Fanout** | `PublicationBus` | [`src/engine/publication_bus.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/publication_bus.py) | 🟢 Canonical |
| **Production API Gateway** | `src.api.app:app` (FastAPI) | [`src/api/app.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/app.py) | 🟢 Canonical |
| **RBAC Security & Rate Limit**| `EnvAuthManager` & `RateLimiter` | [`src/security/auth_manager.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/security/auth_manager.py), [`src/security/policy.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/security/policy.py) | 🟢 Canonical |
| **Telemetry & Metrics** | `MetricsRegistry` & Middleware | [`src/observability/metrics.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/observability/metrics.py), [`src/observability/middleware.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/observability/middleware.py) | 🟢 Canonical |

---

## 3. Entrypoint Classification & Inventory

| Entrypoint | File Path | Framework / Protocol | Purpose | Docker Used? | Docs Used? | Classification |
|---|---|---|---|---|---|---|
| **Production API** | [`src/api/app.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/app.py) | FastAPI (ASGI / Uvicorn) | Authoritative HTTP & WebSocket API Gateway | **Yes (Dockerfile)** | **Yes** | 🟢 **CANONICAL** |
| **Unified Feed Engine**| [`src/engine/unified_chain.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/unified_chain.py)| Async Python | Orchestrator connecting Swarm, Pipeline, and Bus | Indirectly | **Yes** | 🟢 **CANONICAL** |
| **Main Aggregator CLI**| [`main.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/main.py) | Async Python | Dev launcher running aggregator + supervised API | No | **Yes** | 🟡 **HYBRID / DEV WRAPPER** |
| **Main Engine Server** | [`main_engine.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/main_engine.py) | aiohttp.web (Port 8080) | Early monolith server with in-memory ring buffer | No | Legacy | 🔴 **LEGACY / DEPRECATED** |
| **Legacy Dead API** | [`src/api/main.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/main.py) | FastAPI v1.0 | Deprecated early API surface superseded by `src.api.app:app` | No | No | 🔴 **LEGACY / DEPRECATED** |
| **Interactive TUI CLI** | [`cli.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/cli.py) | Rich Console | Terminal user interface for manual exploration | No | Optional | 🔵 **UTILITY** |
| **Telegram Bot Client**| [`telegram_feeder_bot.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/telegram_feeder_bot.py)| aiohttp client | Remote delivery consumer connecting via SSE | No | Optional | 🔵 **CLIENT / UTILITY** |
| **Desktop GUI** | [`gui_qt/app_qt_migrated.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/gui_qt/app_qt_migrated.py)| PyQt6 | Desktop GUI client for local reading | No | Optional | 🔵 **CLIENT / GUI** |

---

## 4. Authoritative Production Startup Sequences

### A. Production Container Deployment (Docker / Compose)
1. **Container Startup**: `uvicorn src.api.app:app --host 0.0.0.0 --port 8000` (executed as non-root user `technews`).
2. **Lifespan Initialization** ([`src/api/app.py:lifespan`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/app.py#L292-L325)):
   - Initializes `SqliteEngine` with canonical WAL settings (`TECHNEWS_DB_PATH` or `TECHNEWS_CANONICAL_DB_PATH`).
   - Executes database schema initialization (Articles, Tech Events, FTS5 Virtual Tables, Indexes).
   - Injects `SqliteArticleRepository` and `SqliteEventRepository` into FastAPI app state and route dependency injection.
   - Loads RBAC authentication credentials from environment variables (`TECHNEWS_ADMIN_API_KEY`, `TECHNEWS_RW_API_KEY`, `TECHNEWS_RO_API_KEY`).
   - Starts Prometheus telemetry middleware.
3. **Health & Liveness Probes**:
   - `GET /health` returns `200 OK` (Liveness / Container orchestration).
   - `GET /health/detailed` audits SQLite connectivity and active row counts.
   - `GET /metrics` outputs valid Prometheus scrape text.

### B. Ingestion Swarm & Continuous Processing Worker
1. **Worker Process Startup**: Launches `UnifiedFeedChainEngine` ([`src/engine/unified_chain.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/unified_chain.py)).
2. **Coordinator Lease Acquisition**: Leases source IDs via `SqliteSwarmCoordinator` ([`src/zombies/coordinator.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/coordinator.py)) preventing split-brain ingestion across workers.
3. **Execution Loop**: Fetches observations via `ZombieSwarm` $\to$ processes observations through `CanonicalPipelineRunner` (S01–S11) $\to$ commits transactions atomically to `SqliteEngine` (S10) $\to$ emits real-time events to `PublicationBus` (S11).

---

## 5. Security & Authentication Contract

### Fail-Closed Principle
1. **Production Mode (`TECHNEWS_ENV=production`)**:
   - `API_ALLOW_ANONYMOUS` defaults to `false`.
   - Every protected data endpoint (`/articles`, `/events`, `/search`, `/sentiment`, `/feed/latest`) requires a valid `X-API-Key` header.
   - Missing or empty API keys result in **HTTP 401 Unauthorized**.
   - Insufficient role or invalid keys result in **HTTP 403 Forbidden** or **401 Unauthorized**.
2. **Environment Variable Alignment**:
   - `TECHNEWS_ADMIN_API_KEY`: Configures the administrator credential (`Role.ADMIN`).
   - `TECHNEWS_RW_API_KEY`: Configures read-write ingestion client credential (`Role.READ_WRITE`).
   - `TECHNEWS_RO_API_KEY`: Configures read-only consumer credential (`Role.READ_ONLY`).
3. **Public Endpoint Whitelist**:
   - `/health`, `/health/detailed`
   - `/metrics`
   - `/docs`, `/redoc`, `/openapi.json`

---

## 6. Migration & Legacy Deprecation Plan

To prevent regression while maintaining backward compatibility:
1. **Do Not Delete Legacy Files Immediately**: Keep `main_engine.py`, `src/api/main.py`, and `main.py` in place.
2. **Mark Deprecations**: Add explicit deprecation warnings and cross-references to `docs/CANONICAL_RUNTIME.md` in legacy entrypoint docstrings.
3. **Align Dockerfile & Compose**: Standardize `Dockerfile` and `docker-compose.yml` to target exclusively `src.api.app:app` and canonical environment variables.
4. **Future Controlled Deletion Gate**: Plan removal of legacy entrypoints for Phase 9 after production stability soak completes.
