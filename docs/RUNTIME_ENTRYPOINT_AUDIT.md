# Runtime Entrypoint Forensic Audit

**Authoritative Entrypoint Graph & Concurrency Mapping**  
**Phase**: Phase 8 Engineering Hardening — Gate 8E-H3  
**Status**: 🟢 COMPLETE & AUTHORITATIVE  
**Date**: `2026-08-17`  

---

## 1. Executive Summary & Runtime Process Graph

This audit provides an exhaustive forensic map of every entrypoint, server listener, background ingestion task, and process/thread model across the repository.

```text
                                  CONTAINER / HOST ENVIRONMENT
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     ▼                                                     ▼
     ┌───────────────────────────────┐                     ┌───────────────────────────────┐
     │      CANONICAL API PROCESS    │                     │   CANONICAL INGESTION WORKER  │
     │      (uvicorn src.api.app:app)│                     │    (python -m src.worker)     │
     │                               │                     │                               │
     │  • FastAPI (ASGI on Port 8000)│                     │  • UnifiedFeedChainEngine     │
     │  • Prometheus (/metrics)      │                     │  • SourceRegistry             │
     │  • Health Probe (/health)     │                     │  • ZombieSwarm (RSS/Web/APIs) │
     │  • RBAC Auth & Rate Limiting  │                     │  • SqliteSwarmCoordinator     │
     │  • Read/Search Endpoints      │                     │  • S01–S11 Canonical Pipeline │
     │  • Read-Only / WAL DB Client  │                     │  • Read-Write WAL DB Engine   │
     │  • PublicationBus Subscriptions│                    │  • Real-Time Event Dispatch   │
     └───────────────┬───────────────┘                     └───────────────┬───────────────┘
                     │                                                     │
                     └──────────────────────────┬──────────────────────────┘
                                                │
                                                ▼
                               ┌─────────────────────────────────┐
                               │     SHARED SQLITE STORAGE       │
                               │      (/data/technews.db)        │
                               │  WAL Mode + NORMAL Synchronous  │
                               │  Foreign Keys + 64MB Page Cache │
                               └─────────────────────────────────┘
```

---

## 2. Complete Entrypoint Inventory & Forensic Classification

| Entrypoint Target | Command / Invocation | Underlying Framework | Network Listeners | Background Tasks / Loops | Production Reachable? | Classification |
|---|---|---|---|---|---|---|
| **Canonical API** | `uvicorn src.api.app:app --port 8000` | FastAPI / Starlette / Uvicorn | `0.0.0.0:8000` (HTTP, WS) | In-memory `PublicationBus` fanout | **Yes (Docker / Compose)** | 🟢 **CANONICAL PRODUCTION** |
| **Canonical Ingestion Worker** | `python -m src.worker` | Asyncio / Swarm Orchestrator | None (Outbound HTTP/HTTPS only) | `ZombieSwarm` autonomous hunting loops + `CanonicalPipelineRunner` S01–S11 | **Yes (Docker / Compose)** | 🟢 **CANONICAL PRODUCTION** |
| **Unified Chain Engine** | `src/engine/unified_chain.py` | Async Python container | None | Swarm callbacks $\to$ Pipeline S01–S11 $\to$ SQLite commit | Indirectly via `src.worker` | 🟢 **CANONICAL COMPONENT** |
| **Legacy Aggregator** | `python main.py` | Python / Multiprocessing | Port 8000 if `--with-api` | `ScraperScheduler` + direct `article_repo.save_articles()` (Bypasses S01–S11) | No | 🔴 **LEGACY / DEPRECATED** |
| **Legacy Engine Server**| `python main_engine.py` | aiohttp.web (Port 8080) | `0.0.0.0:8080` (HTTP, SSE) | `UnifiedFeedChainEngine` + `ArticleRingBuffer` | No | 🔴 **LEGACY / DEPRECATED** |
| **Legacy Dead API** | `src/api/main.py` | FastAPI v1.0 | Port 8000 | In-memory rate limiting | No | 🔴 **LEGACY / DEPRECATED** |
| **Interactive TUI CLI** | `python cli.py` | Rich Console | None | Manual interactive search/fetch | Optional local utility | 🔵 **UTILITY / CLI** |
| **Telegram Feeder Bot** | `python telegram_feeder_bot.py` | Asyncio / aiohttp client | None | SSE connection to API / Telegram Bot API | Optional client | 🔵 **EXTERNAL CLIENT** |
| **Desktop GUI** | `python gui_qt/app_qt_migrated.py` | PyQt6 | None | Local GUI client | Optional client | 🔵 **EXTERNAL CLIENT** |

---

## 3. Background Task & Process Concurrency Model

### A. Canonical Production API (`src.api.app:app`)
- **Event Loop**: Single async loop per Uvicorn worker process.
- **Lifespan Startup**:
  - Initializes `SqliteEngine` on `TECHNEWS_DB_PATH` in WAL mode.
  - Initializes schema (Articles, Events, FTS5 Virtual Tables, Leases).
  - Injects `SqliteArticleRepository` and `SqliteEventRepository` into app state.
  - **Zero background scrapers or autonomous hunting loops are spawned.**
- **Lifespan Teardown**:
  - Closes `SqliteEngine` connection pool cleanly (`await canonical_engine.aclose()`).

### B. Canonical Ingestion Worker (`src.worker`)
- **Event Loop**: Dedicated async loop managing autonomous zombie workers.
- **Components Loaded**:
  - `SourceRegistry`: loads ordered source fleet.
  - `ZombieSwarm`: manages individual `ZRss`, `ZWeb`, `ZCorp`, `ZSecurity`, `ZGitHub`, `ZHacker` instances.
  - `SqliteSwarmCoordinator`: leases source IDs using fencing tokens and TTLs to prevent split-brain execution across workers.
  - `CanonicalPipelineRunner`: executes stages S01 (Normalization) through S11 (Publication Bus).
  - `SqliteArticleRepository` & `SqliteEventRepository`: handles transaction commits.
- **Signal Handling**:
  - Intercepts `SIGINT` and `SIGTERM`.
  - Executes `await engine.aclose()` / `await swarm.aclose()`, flushing source health state, canceling zombie tasks, and closing database pools.

---

## 4. Ingestion Loop Isolation & Duplicate Prevention

### Risk Identified: Duplicate Aggregation Loops
Historically, running `main.py` alongside `main_engine.py` could spawn competing scrapers writing uncoordinated records to SQLite.

### Architectural Enforcements:
1. **Container Isolation**: `docker-compose.yml` exclusively launches `uvicorn src.api.app:app` for the API and `python -m src.worker` for the ingestion worker.
2. **API Lifespan Audit**: `src.api.app:app` contains zero background scraper tasks.
3. **Lease Coordination**: If multiple worker processes are launched, `SqliteSwarmCoordinator` prevents duplicate polling of the same source by enforcing single-owner leases with heartbeats.
