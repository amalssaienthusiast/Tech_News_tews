# Phase 5D Architecture Review: API & Legacy EventStore Migration

**Document Type:** Principal Systems Architecture Specification & Audit  
**Phase:** 5D (API & Legacy EventStore Migration)  
**Status:** **APPROVED FOR IMPLEMENTATION**  
**Repository Baseline:** Commit `35fe02f` (Phase 5C completed, 241/241 tests passing)  
**Authority:** Canonical Storage & Pipeline Persistence Architecture  

---

## 1. Executive Verdict

**Verdict: APPROVED FOR IMPLEMENTATION**

The proposed Phase 5D API migration transitions all API event-reading endpoints and real-time Server-Sent Events (SSE) streaming paths from the legacy, synchronous/threaded `EventStore` to the canonical asynchronous `EventRepositoryProtocol` (`SqliteEventRepository`). 

Key findings of the architectural audit:
1. **Zero Breaking Schema Changes:** The existing API response contract (`TechEventResponse`, `TimelineEntryResponse`, `EventSourceResponseModel`) is 100% compatible with the canonical `TechEvent` aggregate domain model.
2. **True Non-Blocking Async I/O:** Replaces threadpool offloading (`asyncio.to_thread`) in legacy `EventStore` with native `aiosqlite` non-blocking transactions in `SqliteEventRepository`.
3. **Repository Injection via FastAPI `Depends`:** Establishes a clean dependency injection pattern using `get_event_repository()` with a backwards-compatible `set_event_repository()` and `set_event_store()` compatibility bridge.
4. **Zero Legacy Deletion:** Retains `src/events/event_store.py`, `src/database.py`, and `src/db_storage/` in place without deletion to preserve legacy test fixtures and background utilities until Phase 5E/5F.

---

## 2. Current vs. Target API Architecture

### Current Architecture (Phase 5C Baseline)
```text
┌────────────────────────────────────────────────────────┐
│               CANONICAL PIPELINE (S01-S11)             │
│   S07 Hydration ◄─── SqliteEventRepository ──► S10     │
└───────────────────────────▲────────────────────────────┘
                            │ (canonical_events.db)
                            │
┌───────────────────────────▼────────────────────────────┐
│                    API LAYER (CURRENT)                 │
│                                                        │
│  GET /v1/events ──► get_event_store()                  │
│                            │                           │
│                            ▼                           │
│                 Legacy EventStore (sync)               │
│                            │ (asyncio.to_thread)       │
│                            ▼                           │
│                 data/zombie_events.db                  │
│                                                        │
│  GET /v1/events/stream ──► PublicationBus              │
│                            │                           │
│                            ▼ (fallback load_event)     │
│                 Legacy EventStore                      │
└────────────────────────────────────────────────────────┘
```
*Discrepancy:* The canonical pipeline writes to `canonical_events`, while the API still reads from the legacy `zombie_events.db` via `EventStore`, creating a split-brain storage anomaly.

### Target Architecture (Phase 5D)
```text
┌────────────────────────────────────────────────────────┐
│               CANONICAL PIPELINE (S01-S11)             │
│   S07 Hydration ◄─── SqliteEventRepository ──► S10     │
└───────────────────────────▲────────────────────────────┘
                            │
                            │ (Single Canonical Database)
                            ▼
┌────────────────────────────────────────────────────────┐
│                   SQLITE ENGINE (WAL)                  │
│       canonical_events, canonical_event_sources        │
└───────────────────────────▲────────────────────────────┘
                            │
                            │ (EventRepositoryProtocol)
                            ▼
┌────────────────────────────────────────────────────────┐
│                     API LAYER (5D)                     │
│                                                        │
│  FastAPI Router (src/api/routes/events.py)             │
│  ├── GET /v1/events ──► EventRepositoryProtocol        │
│  │                        └── get_active_events()      │
│  │                        └── get_events_by_entity()   │
│  │                                                     │
│  └── GET /v1/events/stream ──► PublicationBus          │
│                                 └── get_event() (async)│
│                                                        │
│  Dependency Injection:                                 │
│  - get_event_repository() -> EventRepositoryProtocol   │
│  - set_event_repository(repo)                          │
│                                                        │
│  Legacy Compatibility Bridge:                          │
│  - get_event_store() / set_event_store() (shim)        │
└────────────────────────────────────────────────────────┘
```

---

## 3. Complete EventStore Consumer & Route Map

An exhaustive codebase audit mapped all consumers of `EventStore`:

| Component | File Path | Usage Description | Target 5D Action |
| :--- | :--- | :--- | :--- |
| **API Events Router** | `src/api/routes/events.py` | Imports `EventStore`, `get_event_store()`, queries events | **MIGRATE** to `EventRepositoryProtocol` |
| **API Main Application** | `src/api/main.py` | Mounts `events_router` | **PRESERVE** (mounts migrated router) |
| **API Hardened App** | `src/api/app.py` | Production app entrypoint | **PRESERVE** (mounts migrated router) |
| **Publication Bus SSE** | `src/api/routes/events.py:event_stream` | Fallback event ID lookup on SSE payload | **MIGRATE** to `await repo.get_event()` |
| **Legacy EventStore Definition** | `src/events/event_store.py` | Core class definition | **RETAIN** intact for compatibility |
| **Test Fixtures** | `tests/test_event_brain.py` | Uses domain types, not `EventStore` | **PRESERVE** |

---

## 4. API Endpoint Migration Matrix

| Endpoint | Method | Auth Required | Current Legacy Path | Target 5D Canonical Path | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/v1/events` | `GET` | Yes (`X-API-Key`) | `store.load_active_events(limit)` | `await repo.get_active_events(limit)` | **REQUIRED** |
| `/v1/events?entity={e}` | `GET` | Yes (`X-API-Key`) | `store.load_events_by_entity(e, limit)` | `await repo.get_events_by_entity(e, limit)` | **REQUIRED** |
| `/v1/events/{id}` | `GET` | Yes (`X-API-Key`) | *(New endpoint)* | `await repo.get_event(event_id)` | **RECOMMENDED** |
| `/v1/events/stream` | `GET` | No (SSE stream) | `store.load_event(id)` (sync) | `await repo.get_event(id)` (async) | **REQUIRED** |
| `/v1/events/stats` | `GET` | Yes (`X-API-Key`) | `store.get_stats()` | `await repo.get_stats()` | **RECOMMENDED** |

---

## 5. Canonical-to-API Field & Response DTO Mapping

The response DTOs in `src/api/routes/events.py` map 1:1 to the canonical `TechEvent` domain aggregate:

```python
class TimelineEntryResponse(BaseModel):
    timestamp: str
    headline: str
    source_name: str
    source_url: str
    confidence_at_time: float
    entry_type: str

class EventSourceResponseModel(BaseModel):
    title: str
    url: str
    source_name: str
    is_primary: bool

class TechEventResponse(BaseModel):
    id: str
    headline: str
    first_seen: str
    last_updated: str
    entities: List[str]
    topics: List[str]
    confidence: float
    status: str
    freshness: str
    freshness_score: float
    source_count: int
    primary_source: Optional[str] = None
    timeline: List[TimelineEntryResponse]
    sources: List[EventSourceResponseModel]
```

### Direct Field Mapping Table:
| `TechEventResponse` JSON Field | Canonical `TechEvent` Property | Transformation Rule |
| :--- | :--- | :--- |
| `id` | `event.id` | String pass-through |
| `headline` | `event.headline` | String pass-through |
| `first_seen` | `event.first_seen` | `event.first_seen.isoformat()` |
| `last_updated` | `event.last_updated` | `event.last_updated.isoformat()` |
| `entities` | `event.entities` | `list(event.entities)` |
| `topics` | `event.topics` | `list(event.topics)` |
| `confidence` | `event.confidence` | `float(event.confidence)` |
| `status` | `event.status` | `event.status.value` (e.g. `"corroborated"`) |
| `freshness` | `event.freshness` | `event.freshness.value` (e.g. `"fresh"`) |
| `freshness_score` | `event.freshness_score` | `float(event.freshness_score)` |
| `source_count` | `event.source_count` | `len(event.sources)` (computed property) |
| `primary_source` | `event.primary_source` | String / Optional |
| `timeline` | `event.timeline` | Map `TimelineEntry` to `TimelineEntryResponse` |
| `sources` | `event.sources` | Map `EventSourceEvidence` to `EventSourceResponseModel` |

---

## 6. Critical Architectural Questions Resolved

### A. Repository Boundary
*Recommendation: DIRECT DEPENDENCY VIA FASTAPI DEPENDENCY INJECTION (**REQUIRED**)*  
The API routes in `src/api/routes/events.py` should depend directly on `EventRepositoryProtocol` via FastAPI's `Depends(get_event_repository)`. Introducing an intermediate service layer is unnecessary overhead at this stage, as the repository protocol already exposes high-level aggregate queries (`get_active_events`, `get_events_by_entity`, `get_event`, `get_stats`).

### B. Read vs. Write Models
*Recommendation: EXPLICIT API DTO MAPPING (**REQUIRED**)*  
The API MUST NOT return raw `TechEvent` domain dataclasses directly. It must map them through `TechEventResponse.from_domain(event: TechEvent)` to guarantee stable JSON serialization, ISO-8601 UTC date formatting, enum string value conversion, and decoupling of internal domain invariants from external API contracts.

### C. Legacy EventStore Strategy
*Recommendation: DEPRECATE WITH COMPATIBILITY SHIM (**REQUIRED**)*  
Do NOT delete `src/events/event_store.py`. Retain `EventStore` in `src/events/` as an untracked legacy utility. Provide a fallback bridge `set_event_store()` in `src/api/routes/events.py` that emits a deprecation warning while converting legacy configurations.

### D. Transaction & Write Semantics
*Recommendation: ATOMIC REPOSITORY WRITES (**REQUIRED**)*  
The API is currently read-only (`GET` endpoints and SSE streams). Any administrative write endpoints added in the future must route through `await repository.save_event(event)`, which executes inside `BEGIN IMMEDIATE ... COMMIT` transactions in `SqliteEventRepository`.

### E. Pagination & Query Limits
*Recommendation: BOUNDED PARAMETER VALIDATION (**REQUIRED**)*  
Enforce `limit: int = Query(50, ge=1, le=200)` on all list endpoints. Preserve pagination semantics by leveraging SQLite's indexed `ORDER BY last_updated DESC LIMIT ?` queries.

### F. Serialization & Timezone Integrity
*Recommendation: UTC ISO-8601 ENFORCEMENT (**REQUIRED**)*  
All timestamps (`first_seen`, `last_updated`, `discovered_at`, `timestamp`) must be serialized with explicit timezone offset or ISO-8601 `Z`/`+00:00` notation.

---

## 7. Security Analysis

1. **Authentication & Authorization:** All non-streaming event endpoints require valid `X-API-Key` headers verified via `verify_api_key`.
2. **SQL Injection Prevention:** `SqliteEventRepository` exclusively uses parameterized queries (`?` placeholders). No user-supplied string formatting or raw SQL concatenation exists.
3. **DoS & Resource Exhaustion Protection:** 
   - Strict bounds on query parameters: `limit` capped at 200 items.
   - `entity` parameter sanitized and checked for maximum length (100 chars).
   - Rate limiting enforced via `RateLimiter` per tier (free/pro/enterprise).
4. **Information Leakage Prevention:** Database exceptions are caught, logged internally with correlation IDs, and translated to standard `HTTPException(status_code=500, detail="Internal storage error")` without exposing raw SQL tracebacks.

---

## 8. Performance & Concurrency Analysis

1. **WAL Concurrency:** The canonical SQLite database runs under `PRAGMA journal_mode = WAL` and `PRAGMA busy_timeout = 10000`. API read queries execute concurrently with S10 persistence write transactions without lock contention.
2. **Covering Indexes:** The canonical SQLite schema in `src/storage/schema_sqlite.sql` already provides the necessary indexes:
   - `idx_canonical_events_status` on `status`
   - `idx_canonical_events_last_updated` on `last_updated DESC`
   - `idx_canonical_events_entities` (via JSON / entity queries)
3. **Non-Blocking SSE Streaming:** The `/v1/events/stream` endpoint consumes from `PublicationBus` in memory and only queries `get_event()` on cache misses or string payloads, minimizing database load.

---

## 9. Comprehensive Testing Strategy

Subphase 5D will introduce a dedicated test suite `tests/test_api_events_migration.py` covering:
1. **Repository Injection:** Verifying `get_events` resolves against an injected `SqliteEventRepository`.
2. **Active Events Query:** Verifying `GET /v1/events` returns formatted `TechEventResponse` items matching database contents.
3. **Entity Filtering:** Verifying `GET /v1/events?entity=OpenAI` filters correctly.
4. **Single Event Lookup:** Verifying `GET /v1/events/{id}` returns 200 with full timeline/sources, or 404 for missing IDs.
5. **SSE Stream Emission:** Verifying `/v1/events/stream` emits structured SSE events upon `PublicationBus` broadcasts.
6. **Error Isolation:** Verifying database errors return HTTP 500 without leaking SQL internals.
7. **Backwards Compatibility:** Verifying `set_event_store()` compatibility bridge functions properly.

---

## 10. Revised 5D Implementation Plan

```text
=============================================================================
SUBPHASE 5D STEP-BY-STEP EXECUTION
=============================================================================

Step 1: Dependency Injection in API Routes (src/api/routes/events.py)
  - Replace `_shared_event_store: Optional[EventStore]` with:
      `_shared_repository: Optional[EventRepositoryProtocol]`
  - Implement `get_event_repository() -> EventRepositoryProtocol`
  - Implement `set_event_repository(repo: EventRepositoryProtocol) -> None`
  - Add compatibility bridge `get_event_store()` and `set_event_store(store)`

Step 2: Migrate Route Handlers to Async EventRepositoryProtocol
  - Update `get_events()` to `await repo.get_active_events(limit)` / `get_events_by_entity()`
  - Add `get_event_by_id(event_id)` endpoint: `await repo.get_event(event_id)`
  - Add `get_event_stats()` endpoint: `await repo.get_stats()`
  - Update SSE `event_stream()` to `await repo.get_event(id)`

Step 3: Response Serialization Enhancements
  - Implement `TechEventResponse.from_domain(event: TechEvent)`
  - Implement `TimelineEntryResponse.from_domain(entry: TimelineEntry)`
  - Implement `EventSourceResponseModel.from_domain(source: EventSourceEvidence)`

Step 4: Create Comprehensive 5D Test Suite (tests/test_api_events_migration.py)
  - Verify all 5D requirements with FastAPITestClient / AsyncClient against SqliteEventRepository.

Step 5: Full Regression & Gate Verification
  - Run focused 5D tests.
  - Run full suite (241 existing tests + new 5D tests).
  - Verify zero architectural violations or unpermitted imports.
```

---

## 11. Acceptance Criteria & Quality Gate

- [ ] `src/api/routes/events.py` strictly uses `EventRepositoryProtocol` for all database interactions.
- [ ] No direct imports of `sqlite3`, `aiosqlite`, or raw SQL inside `src/api/routes/events.py`.
- [ ] Legacy compatibility methods (`get_event_store`, `set_event_store`) remain available.
- [ ] All API response shapes (`TechEventResponse`) maintain 100% backwards compatibility.
- [ ] End-to-end integration test passes: Pipeline writes event $\to$ API reads event with full fidelity.
- [ ] All previous 241 tests continue passing without regression.
- [ ] `PHASE_5D_IMPLEMENTATION_REPORT.md` generated with complete audit results.

---

## 12. Classification of Recommendations

| Item | Recommendation | Classification |
| :--- | :--- | :--- |
| 1 | Replace `EventStore` in `src/api/routes/events.py` with `EventRepositoryProtocol` | **REQUIRED** |
| 2 | Use `TechEventResponse.from_domain()` mapper for serialization | **REQUIRED** |
| 3 | Maintain `get_event_store()` / `set_event_store()` as compatibility bridge | **REQUIRED** |
| 4 | Add `GET /v1/events/{id}` single-event lookup endpoint | **RECOMMENDED** |
| 5 | Add `GET /v1/events/stats` diagnostics endpoint | **RECOMMENDED** |
| 6 | Delete `src/events/event_store.py` during 5D | **DANGEROUS / FORBIDDEN** |
| 7 | Modify Phase 4 acquisition zombies | **DANGEROUS / FORBIDDEN** |
| 8 | Delete `src/db_storage/` or `src/database.py` during 5D | **DEFERRED (Phase 5F)** |
