# Phase 5F-E Architecture Review: Legacy `src/events/` EventStore Retirement

**Milestone**: Subphase 5F-E (5F-E1 through 5F-E6)  
**Status**: ARCHITECTURE REVIEW — AWAITING GATE AUTHORIZATION  
**Target Package**: `src/events/` (`event_store.py`, `event_types.py`, `__init__.py`)  
**Git Baseline**: `78497ac` (Subphase 5F-D committed; clean working tree)  
**Baseline Test Suite**: 162/162 core canonical tests passing  

---

## 1. Executive Summary

Subphase **5F-E** is the second decommissioning gate in Phase 5F. Its mission is to retire and permanently remove the legacy event storage implementation in `src/events/` and remove deprecated compatibility bridges (`get_event_store()`, `set_event_store()`).

In Phase 5A through 5D:
1. All canonical domain models and enums were centralized into `src/domain/` (`TechEvent`, `EventSourceObservation`, `TimelineEntry`, `EventStatus`, `FreshnessLevel`).
2. Canonical asynchronous persistence was implemented in `SqliteEventRepository` on `canonical_events.db` (`tech_events`, `event_sources`, `timeline_entries`) via `EventRepositoryProtocol`.
3. S07 pipeline clustering and cold-start hydration were converted to `ActiveEventStore` and `SqliteEventRepository`.
4. FastAPI events routes (`/v1/events`, `/v1/events/stream`) were wired exclusively to `EventRepositoryProtocol`.

As proven in this audit, **no active production subsystem depends on `src/events/event_store.py` or legacy `EventStore`**.

```
                   CURRENT PRODUCTION ARCHITECTURE
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
Pipeline Runner Stage S07    FastAPI Event Delivery     SSE Live Stream
 (ActiveEventStore Hydration)   (/v1/events endpoints)   (/v1/events/stream)
        │                        │                        │
        └────────────────────────┼────────────────────────┘
                                 ▼
                      EventRepositoryProtocol
                                 │
                                 ▼
                       SqliteEventRepository
                                 │
                                 ▼
                        SqliteEngine (WAL)
                                 │
                                 ▼
                        canonical_events.db

            ===========================================
            DECOMMISSION TARGET IN 5F-E:
              ✗ src/events/event_store.py (DELETION)
              ✗ src/events/event_types.py (DELETION)
              ✗ src/events/__init__.py    (DELETION)
              ✗ get_event_store() / set_event_store() shims (REMOVAL)
              ✗ tests/test_event_brain.py (DELETION)
            ===========================================
```

---

## 2. Inventory of `src/events/` Package Files

| File | Lines | Historical Role | Current Status | Replacement in Canonical Architecture |
|---|---|---|---|---|
| `src/events/event_store.py` | 420 | SQLite table manager for `events.db` with synchronous thread-locking | **Obsolete / Dead** | `SqliteEventRepository` (`src/storage/sqlite_event_repository.py`) on `SqliteEngine` |
| `src/events/event_types.py` | 27 | Re-export facade for legacy types (`TechEvent`, `EventSource`) | **Obsolete / Dead** | `src/domain/models.py` & `src/domain/enums.py` |
| `src/events/__init__.py` | 281 | Legacy dataclasses and enums (`TechEvent`, `EventStatus`, `FreshnessLevel`) | **Obsolete / Dead** | `src/domain/models.py` & `src/domain/enums.py` |

---

## 3. Comprehensive Dependency Audit

### 1. Production Source Audit (`src/`)
- `src/api/routes/events.py`: Contains deprecated `get_event_store()` / `set_event_store()` functions that had a fallback `from src.events.event_store import EventStore`.
  - *Action*: Remove `get_event_store()` and `set_event_store()`.
- `src/pipeline/stages/s07_clustering.py`: Uses `ActiveEventStore` (in-memory clusterer store) which hydrates from `EventRepositoryProtocol`. Zero imports of `src.events`.
- `src/pipeline/runner.py`: Uses `ActiveEventStore`. Zero imports of `src.events`.
- `src/domain/*`: Zero imports of `src.events`.
- `src/storage/*`: Zero imports of `src.events`.
- `src/zombies/*`: Zero imports of `src.events`.

### 2. GUI & Root Entrypoints Audit
- `gui_qt/`: Zero imports of `src.events` or `EventStore`.
- `main.py`, `main_engine.py`, `cli.py`, `telegram_feeder_bot.py`: Zero imports of `src.events` or `EventStore`.

### 3. Test Suite Dependencies
| Test File | Usage | Required Action in 5F-E |
|---|---|---|
| `tests/test_event_brain.py` | Phase 0 legacy unit test importing non-existent `EntityExtractor`, `EventClusterer`, `src.events.event_types` | **Delete** (Obsolete test file) |
| `tests/test_api_events_migration.py` | Tests `get_event_store()` / `set_event_store()` deprecation bridge | **Update** to assert shims are removed and `get_event_repository()` is authoritative |
| `tests/test_pipeline_protocols.py` | Imports `from src.events.event_types import EventSource` for adapter testing | **Update** to use a local `MockEventSource` dataclass |
| `tests/test_canonical_pipeline_runner.py` | Imports `from src.events.event_types import EventSource` in 1 test | **Update** to use canonical `SourceObservation` |
| `tests/test_architecture_boundaries.py` | Enforces zombies layer doesn't import `src.events` | **Expand** with `TestEventsArchitectureBoundaries` asserting `src/events` does not exist |

---

## 4. Compatibility Shim Retirement Path

In `src/api/routes/events.py`:
- `get_event_repository()` and `set_event_repository()` are the **only** supported dependency injection points.
- Deprecated shims `get_event_store()` and `set_event_store()` will be removed entirely.
- The route will have **zero** references to any "Store" concept, completing the migration to the Repository pattern.

---

## 5. Subphase 5F-E Step-by-Step Execution Plan

### Step 5F-E1: Compatibility Shim Removal & Route Modernization
1. In `src/api/routes/events.py`: Remove `get_event_store()` and `set_event_store()`.
2. In `tests/test_api_events_migration.py`: Update `test_legacy_compatibility_bridge()` to verify that `get_event_store` is no longer in `src.api.routes.events.__all__` or exported.
3. In `tests/test_pipeline_protocols.py`: Replace `from src.events.event_types import EventSource` with a dedicated local mock test structure.
4. In `tests/test_canonical_pipeline_runner.py`: Replace `EventSource` with `SourceObservation`.

### Step 5F-E2: Physical Deletion of `src/events/` and Obsolete Tests
1. Remove `src/events/` package directory:
   ```bash
   rm -rf src/events
   ```
2. Remove obsolete `tests/test_event_brain.py`:
   ```bash
   rm -f tests/test_event_brain.py
   ```

### Step 5F-E3: Architecture Boundary Invariant Enforcement
Add `TestEventsArchitectureBoundaries` to `tests/test_architecture_boundaries.py`:
- Permanent assertion that `src/events` directory does not exist on filesystem.
- Permanent AST assertion that zero `.py` files in `src/`, `gui_qt/`, or root import `src.events` or `events`.

### Step 5F-E4: Verification Suite Execution
1. **Gate A**: Targeted architecture tests (`test_architecture_boundaries.py`, `test_api_events_migration.py`, `test_pipeline_protocols.py`).
2. **Gate B**: Canonical storage tests (`test_sqlite_*.py`, `test_api_*.py`, `test_persistence_hydration.py`, etc.).
3. **Gate C**: Complete regression suite (`pytest -k "not test_resilience"`).
4. **Gate D**: Python compilation & import smoke tests (`compileall src` + import test script).

### Step 5F-E5: Implementation Report & Milestone Commit
1. Generate `PHASE_5F_E_IMPLEMENTATION_REPORT.md`.
2. Commit with message: `"phase-5f-e: retire and remove legacy events package"`.
3. Maintain zero GitHub push invariant.

---

## 6. Safety & Boundary Invariants

- **Non-Destructive for Other Layers**: `src/database.py` and `src/scraper.py` remain intact for Subphase 5F-F.
- **Single Source of Truth**: All event intelligence domain types reside in `src/domain/models.py` and `src/domain/enums.py`.
- **Event Persistence**: All event persistence runs via `SqliteEventRepository` on `canonical_events.db`.
- **Test Integrity**: Full regression suite must pass with 0 collection or runtime errors.
