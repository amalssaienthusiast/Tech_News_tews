# Phase 2A Architecture: Domain Layer & Boundary Isolation

**Document Status**: Phase 2A Design Specification  
**Authority**: Architecture Lead  
**Scope**: Core Domain Model, Package Hierarchy, Dependency Inversion, Boundary Isolation

---

## 1. Executive Architecture Summary

The Tech News Scrapper system is transitioning from a fragmented, dual-pipeline architecture (legacy `Article`/`FeedChain` vs. `EventSource`/`TechEvent`) to a **Domain-Driven Design (DDD) layered architecture**.

In the target architecture:
1. **Domain Objects are the Single Source of Truth**: All components communicate through 8 canonical domain contracts.
2. **Strict Downward Dependency Rule**: Outer layers may depend on inner layers; inner layers MUST NEVER depend on outer layers.
3. **Decoupled Delivery via Publication Bus**: Delivery surfaces (API, SSE, Telegram, WebSockets) consume domain events through an asynchronous `PublicationBus`.
4. **Isolated Desktop GUI**: The desktop UI interacts with the system exclusively through a defined client contract, with zero server-side imports from `gui_qt/`.

---

## 2. Target Layered Architecture Hierarchy

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 5: Delivery & Interfaces                                         │
│ - REST API (FastAPI: src/api/)                                         │
│ - Telegram Feeder Bot (telegram_feeder_bot.py)                         │
│ - Realtime Streams (SSE: src/realtime/sse_broadcaster.py, WebSocket)   │
│ - Desktop GUI (gui_qt/) [Isolated client runtime]                      │
│ - CLI & Daemon Runners (main_engine.py)                                │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (depends on)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 4: Pipeline & Orchestration                                      │
│ - Canonical Pipeline Stages (src/engine/pipeline.py)                   │
│ - Normalizer, FreshnessGate, RelevanceClassifier, QualityGate          │
│ - DedupGate (MinHash / Bloom), EventClusterer, ConfidenceEngine        │
│ - Asynchronous Content Enhancer (src/engine/content_enhancer.py)       │
│ - Publication Bus (src/engine/publication_bus.py)                      │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (depends on)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 3: Acquisition & Ingestion                                       │
│ - Autonomous Swarm (src/zombies/swarm.py)                              │
│ - Specialized Zombie Collectors (src/zombies/z_*.py)                   │
│ - Multi-Tier Web Acquisition & Bypass (src/bypass/bypass_resolver.py)  │
│ - Source Health & Rate Limit State (src/resilience/source_health.py)   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (depends on)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 2: Persistence & Storage                                         │
│ - Async Database Engine (src/db_storage/async_database.py)             │
│ - Domain Repositories (src/db_storage/repositories.py)                 │
│ - Ephemeral Cache & Redis State (src/db_storage/ephemeral_store.py)    │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (depends on)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Core Domain Contracts & Types (src/domain/)                   │
│ - Pure Domain Entities & Value Objects (Zero External Dependencies)    │
│ - SourceObservation, NormalizedArticle, QualityReport, DedupDecision   │
│ - TechEvent, PublicationEvent, FreshnessLevel, SourceHealth            │
│ - Domain Exceptions & Invariant Validators                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Boundary Violation Elimination Strategy

### 3.1 Violation 1: Engine → API Route Dependency (`unified_chain.py` → `api.routes.events`)
- **Problem**: `unified_chain.py` (L108) imports and calls `broadcast_event_update(event.id)` from `src/api/routes/events.py`. This violates Layer 4 → Layer 5 separation, creating a circular runtime coupling.
- **Remediation**:
  1. The pipeline pushes all cleared articles and detected events to `PublicationBus`.
  2. The API layer subscribes to `PublicationBus` during startup (`app.py` lifespan).
  3. When an event is published, the API's SSE/WebSocket subscriber dispatches it to connected clients.
  4. The engine has **zero imports** from `src/api/`.

```text
[Pipeline: UnifiedChain] ──publish──► [PublicationBus] ◄──subscribe── [API / SSE Route]
                                              ▲
                                              └──subscribe── [Telegram Feeder Bot]
```

### 3.2 Violation 2: Events → Engine Dependency (`event_clusterer.py` → `source_registry.py`)
- **Problem**: Clustering logic had conceptual and import coupling to engine-specific registry structures.
- **Remediation**:
  1. Define `SourceDescriptor` and `SourceTier` in Layer 1 domain contracts (`src/domain/types.py`).
  2. `EventClusterer` operates strictly on `SourceObservation` and `NormalizedArticle` domain models.
  3. `source_registry.py` lives in Layer 3/4 as an implementation of domain source management.

### 3.3 Violation 3: Desktop GUI → Legacy Internal Modules (`gui_qt/` → `src/database.py`, `src/scraper.py`)
- **Problem**: Desktop GUI components directly instantiated legacy synchronous SQLite connections and web scrapers.
- **Remediation**:
  1. Desktop GUI interacts strictly via `TechNewsClient` (HTTP REST/SSE client hitting `http://localhost:8080`).
  2. Alternatively, in standalone local mode, it calls a dedicated async service interface without touching raw SQLite.
  3. Server code and engine entrypoints strictly forbid importing `gui_qt` (enforced via AST import linting).

---

## 4. Import Boundary Enforcement Matrix

The following table defines allowed import directions across the repository:

| From Package | Can Import From | FORBIDDEN To Import From |
|:---|:---|:---|
| `src/domain/` (Layer 1) | `typing`, `dataclasses`, `datetime`, `enum`, `uuid`, `hashlib` | `src/db_storage/`, `src/zombies/`, `src/engine/`, `src/api/`, `gui_qt/`, third-party network libs |
| `src/db_storage/` (Layer 2) | `src/domain/`, `aiosqlite`, `asyncpg`, `pydantic` | `src/zombies/`, `src/engine/`, `src/api/`, `gui_qt/` |
| `src/bypass/`, `src/zombies/` (Layer 3) | `src/domain/`, `aiohttp`, `primp`, `playwright` | `src/engine/`, `src/api/`, `src/db_storage/` (writes go through pipeline/repositories), `gui_qt/` |
| `src/engine/`, `src/events/` (Layer 4) | `src/domain/`, `src/db_storage/`, `src/bypass/`, `src/zombies/` | `src/api/`, `gui_qt/`, `telegram_feeder_bot.py` |
| `src/api/`, `src/realtime/` (Layer 5) | `src/domain/`, `src/engine/` (services/bus only), `src/db_storage/` | `gui_qt/` |
| `gui_qt/` | `src/domain/` (schemas/types only), `requests`/`httpx`/`aiohttp` (HTTP client) | Internal engine internals, direct SQLite database connections |

---

## 5. Failure Semantics & Resilience Model

1. **Fail-Fast Invariant Validation**: Domain objects enforce validation invariants during instantiation. Malformed inputs raise `DomainValidationError` at the boundary rather than corrupting internal state.
2. **Explicit Rejection Reports**: When an article fails quality or deduplication, it is never silently dropped. A structured `QualityReport` or `DedupDecision` is emitted for telemetry and diagnostics.
3. **No Synchronous Database Calls in Async Contexts**: All persistence contracts are asynchronous (`async def`).
4. **Bounded Memory Guarantees**: All in-memory caches and queues implement strict capacity limits (`maxsize`) and LRU/TTL eviction policies.
