# Phase 5A Implementation Report: Storage Protocols, SQLite DDL & Connection Engine

**Subphase:** 5A (Storage Protocols, SQLite DDL & Connection Engine)  
**Branch:** `phase-4-acquisition-zombies`  
**Base Commit:** `f416b2f`  
**Cumulative Test Suite:** `223/223 PASSED` (100% clean, +11 tests added)  
**Status:** **PASS — Ready for Review**  

---

## 1. Overview & Objective

Subphase 5A establishes the minimal, canonical, asynchronous SQLite persistence foundation for the Phase 5 storage architecture. It defines strongly typed asynchronous repository protocols matching the frozen Phase 3/4 domain models, provides the corrected SQLite schema DDL, and implements a non-blocking connection and transaction engine using `aiosqlite`.

---

## 2. Files Created & Git Scope

| File Path | Purpose |
| :--- | :--- |
| `src/storage/__init__.py` | Storage package exports (`SqliteEngine`, `protocols`, constants) |
| `src/storage/protocols.py` | Asynchronous repository protocols (`EventRepositoryProtocol`, `ArticleRepositoryProtocol`, `SourceHealthRepositoryProtocol`) |
| `src/storage/schema_sqlite.sql` | Corrected canonical SQLite DDL (WAL, Foreign Keys, cascading deletes, unique constraints) |
| `src/storage/sqlite_engine.py` | Asynchronous `aiosqlite` connection manager, PRAGMA enforcement, and transaction manager |
| `tests/test_storage_engine.py` | Focused 5A integration and unit tests (11/11 passing) |

### Git Scope Verification
```text
$ git status --short
?? src/storage/
?? tests/test_storage_engine.py

$ git diff --stat
(clean - zero modifications to existing code)
```

---

## 3. Storage Protocols Definition (`src/storage/protocols.py`)

All protocols strictly consume canonical domain models from `src.domain.models` (`TechEvent`, `NormalizedArticle`, `SourceHealth`) with zero invented fields:

- **`EventRepositoryProtocol`:**
  - `save_event(event: TechEvent) -> None`: Atomic upsert of aggregate root + sources + timeline.
  - `get_event(event_id: str) -> Optional[TechEvent]`: Loads complete aggregate by ID.
  - `get_active_events(limit: int = 100) -> List[TechEvent]`: Non-stale events ordered by `last_updated DESC`.
  - `get_events_since(cutoff_utc: datetime, limit: int = 5000) -> List[TechEvent]`: Bounded query for S07 hydration.
  - `get_events_by_entity(entity: str, limit: int = 50) -> List[TechEvent]`: Entity filter query.
  - `delete_event(event_id: str) -> bool`: Cascading delete.
  - `get_stats() -> Dict[str, Any]`: Store telemetry and breakdown.
- **`ArticleRepositoryProtocol`:**
  - `save_article(article: NormalizedArticle) -> None`: Article upsert.
  - `get_article(article_id: str) -> Optional[NormalizedArticle]`: Lookup by ID.
  - `get_article_by_canonical_url(canonical_url: str) -> Optional[NormalizedArticle]`: Lookup by normalized URL.
  - `get_recent_articles(limit: int = 100) -> List[NormalizedArticle]`: Recent article query.
- **`SourceHealthRepositoryProtocol`:**
  - `save_health(health: SourceHealth) -> None`: Resilience state upsert.
  - `get_health(source_id: str) -> Optional[SourceHealth]`: Lookup by source ID.
  - `get_all_health() -> List[SourceHealth]`: Load all health records.

---

## 4. Corrected SQLite Schema (`src/storage/schema_sqlite.sql`)

### 1. `canonical_events` (Aggregate Root)
- **Columns:** `id` (PK), `headline`, `first_seen`, `last_updated`, `entities` (JSON array), `topics` (JSON array), `primary_source`, `confidence`, `importance`, `novelty`, `status`, `freshness`, `freshness_score`, `cluster_id`, `category`, `source_count`, `created_at`.
- **Invariants:** 
  - Derived `TechEvent.is_breaking` is NOT stored as independent mutable state.
  - Indexes on `status`, `freshness`, and `last_updated DESC`.

### 2. `canonical_event_sources` (Child Evidence Entity)
- **Columns:** `id` (PK AUTOINCREMENT), `event_id` (FK), `article_id`, `url`, `title`, `source_name`, `source_tier`, `discovered_at`, `published_at`, `summary`, `image_url`, `is_primary`, `created_at`.
- **Invariants:**
  - `FOREIGN KEY (event_id) REFERENCES canonical_events(id) ON DELETE CASCADE`
  - `UNIQUE(event_id, url)` constraint prevents duplicate source URLs per event.
  - No `zombie_species` column (matches `EventSourceEvidence`).

### 3. `canonical_event_timeline` (Child Timeline Entity)
- **Columns:** `id` (PK AUTOINCREMENT), `event_id` (FK), `timestamp`, `headline`, `source_name`, `source_url`, `confidence_at_time`, `entry_type`, `created_at`.
- **Invariants:**
  - `FOREIGN KEY (event_id) REFERENCES canonical_events(id) ON DELETE CASCADE`

### 4. `canonical_articles` (Normalized Article Entity)
- **Columns:** `id` (PK), `canonical_url` (UNIQUE), `original_url`, `title`, `clean_text`, `summary`, `source_id`, `source_name`, `source_tier`, `zombie_species`, `discovered_at`, `published_at`, `language`, `image_url`, `authors` (JSON), `tags` (JSON), `metadata` (JSON), `created_at`.

### 5. `canonical_source_health` (Resilience State Entity)
- **Columns:** `source_id` (PK), `source_url`, `source_name`, `status`, `consecutive_failures`, `consecutive_successes`, `last_attempt`, `last_success`, `last_status_code`, `cooldown_until`, `rate_limit_reset_at`, `working_bypass_tier`, `updated_at`.

---

## 5. Asynchronous Connection Engine (`src/storage/sqlite_engine.py`)

- **Driver:** `aiosqlite` (non-blocking async SQLite).
- **PRAGMA Enforcement on every connection:**
  - `PRAGMA journal_mode = WAL;` (Concurrent readers during writes).
  - `PRAGMA synchronous = NORMAL;` (Safe, high-throughput durability).
  - `PRAGMA foreign_keys = ON;` (Cascading integrity guarantees).
  - `PRAGMA busy_timeout = 10000;` (10-second automatic backoff to eliminate `database is locked` errors).
- **Context Managers:**
  - `async with engine.connect() as conn:` Non-transactional connection (auto-closed upon exit).
  - `async with engine.transaction() as conn:` Scoped transaction (`BEGIN IMMEDIATE`), auto-commits on success, auto-rolls back on exception.
- **Path Resolution:** Default `data/canonical_events.db`, resolved securely within `DATA_DIR` with auto-creation of parent directories.

---

## 6. Test Suite & Verification Results

### Focused Subphase 5A Tests (`tests/test_storage_engine.py`):
```text
tests/test_storage_engine.py::test_schema_creation_tables_exist PASSED
tests/test_storage_engine.py::test_pragmas_configured_correctly PASSED
tests/test_storage_engine.py::test_idempotent_schema_initialization PASSED
tests/test_storage_engine.py::test_foreign_key_and_cascade_delete PASSED
tests/test_storage_engine.py::test_foreign_key_violation_rejection PASSED
tests/test_storage_engine.py::test_unique_constraint_on_event_sources PASSED
tests/test_storage_engine.py::test_transaction_rollback_on_error PASSED
tests/test_storage_engine.py::test_canonical_articles_table_operations PASSED
tests/test_storage_engine.py::test_canonical_source_health_table_operations PASSED
tests/test_storage_engine.py::test_direct_async_context_manager_lifecycle PASSED
tests/test_storage_engine.py::test_protocols_importable_and_typecheckable PASSED
============================== 11 passed in 0.08s ==============================
```

### Cumulative Test Suite:
- **Baseline (Phase 4):** 212 passed
- **Subphase 5A Tests:** +11 passed
- **Total Cumulative Suite:** **223 passed, 0 failed, 0 errors**

---

## 7. Scope Boundaries & Non-Implementation Verification

- [x] Zero changes to Phase 4 zombie species or swarm.
- [x] Zero changes to existing pipeline stages (S01–S11).
- [x] Zero implementation of `SqliteEventRepository` (reserved for 5B).
- [x] Zero implementation of S07 hydration or S10 integration (reserved for 5C).
- [x] Zero changes to API routes (reserved for 5D).
- [x] Legacy files preserved (`src/events/event_types.py`, `src/events/event_store.py`, `src/db_storage/`, `src/database.py`).
- [x] Zero uncommitted changes to tracked files; local-only working tree.

---

## 8. Subphase 5A Recommendation

**Verdict: PASS ✅**

The asynchronous SQLite persistence foundation meets all architectural requirements, honors domain invariants, and is ready for Subphase 5B (`SqliteEventRepository` & Domain Row Mappers).
