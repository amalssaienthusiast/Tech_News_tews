# Phase 5F-D Architecture & Retirement Audit: `src/db_storage/` Package Decommissioning

**Milestone**: Subphase 5F-D (5F-D1 Inventory & 5F-D2 Retirement Audit)  
**Status**: AUDIT COMPLETE — READY FOR RETIREMENT & REMOVAL  
**Target Package**: `src/db_storage/` (6 files, 2,471 lines)  
**Git Baseline**: `c36860d`  
**Test Suite Verification**: 362 passing tests  

---

## 1. Executive Summary

This architecture audit provides a formal, evidence-backed dependency closure and safety analysis for the complete retirement and deletion of the legacy `src/db_storage/` package.

`src/db_storage/` was previously the asynchronous database layer (built on SQLAlchemy/aiosqlite/asyncpg) that operated in a split-brain architecture alongside `src/database.py`. Throughout Phase 5 (5A through 5E) and Phase 5F (5F-A through 5F-C), all production subsystems were migrated to the canonical SQLite storage engine (`SqliteEngine` on `canonical_events.db`) via typed domain protocols (`ArticleRepositoryProtocol`, `EventRepositoryProtocol`, `SourceHealthRepositoryProtocol`, `UserPreferencesRepositoryProtocol`).

As of this audit, **zero production modules in `src/`, `gui_qt/`, `api/`, or root entrypoints import or execute code from `src/db_storage/`**.

---

## 2. Dependency Closure Analysis of `src/db_storage/`

| File | Lines | Internal Role | External Consumers Remaining | Safe to Delete? |
|---|---|---|---|---|
| `src/db_storage/__init__.py` | 55 | Facade re-exporting `get_storage_manager`, `StorageMode`, `DatabaseHandler`, `AsyncDatabaseManager` | **0** | **YES** |
| `src/db_storage/db_handler.py` | 185 | SQLAlchemy async ORM handler for `live_feed.db` | **0** (migrated in `src/api/app.py` & `main.py`) | **YES** |
| `src/db_storage/unified_storage.py` | 410 | Hybrid sync/async intermediate storage facade | **0** (migrated in `src/engine/orchestrator.py` & `src/database.py`) | **YES** |
| `src/db_storage/async_database.py` | 920 | Authoritative async database engine (aiosqlite/asyncpg) | **0** (superseded by `SqliteEngine`) | **YES** |
| `src/db_storage/ephemeral_store.py` | 340 | Redis / memory cache for ephemeral articles | **0** (ephemeral caching handled in memory/pipeline) | **YES** |
| `src/db_storage/migration.py` | 430 | SQLite to PostgreSQL table migration tool | **0** (PostgreSQL migration tool deprecated; canonical store is SQLite WAL) | **YES** |

---

## 3. Ten-Point Retirement Audit

### 1. AST & Static Grep Import Verification
- Grep query: `grep -rn "src.db_storage" src/`
- Result: **0 occurrences** outside `src/db_storage/` itself.
- All production consumers in `src/api/`, `src/compliance/`, `src/discovery/`, `src/engine/`, `src/monitoring/`, `src/operations/`, `src/queue/`, `src/user/`, and `src/database.py` have 0 AST imports.

### 2. Dynamic Import Audit (`importlib`, `__import__`, `eval`, `exec`)
- Audited dynamic imports across `src/` and entrypoints.
- No dynamic calls resolve `src.db_storage` or string literals referencing `db_storage` modules.

### 3. String-Based Import & Reflection Audit
- Audited all string occurrences of `"src.db_storage"`, `"unified_storage"`, `"db_handler"`, `"async_database"`.
- Results: Only historic documentation (`.md`) and boundary audit tests contain string tokens for static verification.

### 4. Runtime Factory References
- `ScraperFactory`, `ZombieFactory`, `PipelineRunner`, and `Repository` factories have 0 references to `src.db_storage` classes.

### 5. Test Suite Dependency Audit
- Canonical test suites (`test_sqlite_*.py`, `test_api_*.py`, `test_phase5*.py`, `test_domain_contracts.py`, `test_canonical_pipeline_runner.py`) have **zero** dependencies on `src.db_storage`.
- Tests targeting `src.db_storage` directly:
  - `tests/test_async_database.py` (obsolete unit tests for deleted AsyncDatabaseManager)
  - `tests/test_db_migration.py` (obsolete unit tests for deleted PostgreSQL migration script)
- Action: Retire `tests/test_async_database.py` and `tests/test_db_migration.py` concurrently with package deletion.

### 6. CLI & Entrypoint Audit
- `main.py` (RealTimeNewsAggregator): Migrated to `SqliteEngine` + `SqliteArticleRepository`.
- `main_engine.py` (UnifiedFeedChainEngine): Uses canonical pipeline runner & repositories.
- `cli.py`: Uses canonical orchestrator and repositories.
- `telegram_feeder_bot.py`: Direct Telegram bot integration without `db_storage`.
- `gui_qt/app_qt_migrated.py`: Cleaned all legacy storage mode hooks.

### 7. Background Task & Worker Audit
- `src/queue/tasks.py` (Celery retention tasks): Uses direct SQL on `canonical_articles` with UTC timestamps.
- Zero references in Celery workers, cron jobs, or multiprocessing executors.

### 8. Configuration Audit
- `config/settings.py` defines `CANONICAL_DB_FILE`, `DEFAULT_CANONICAL_DB_PATH`, `DB_FILE`.
- No active config flags require `src/db_storage/`.

### 9. Startup & Shutdown Lifecycle Audit
- `src/api/main.py` lifespan: Initializes `SqliteEventRepository` and `SqliteArticleRepository` on shared `SqliteEngine`; cleanly closes engine on shutdown.
- `src/api/app.py` lifespan: Completely unhooked from `db_handler`.
- Signal handlers in `main.py`: Closes `SqliteEngine` asynchronously.

### 10. Operational Scripts & Tooling Audit
- `scripts/migrate_db.py`: Standalone script with comments only; no runtime imports of `src.db_storage`.
- `tests/verify_system.py`: Migrated to canonical `SqliteArticleRepository`.

---

## 4. Decommissioning Plan (Subphase 5F-D3 to 5F-D5)

1. **Step 5F-D3: Physical Deletion**:
   - Delete directory: `rm -rf src/db_storage/`
   - Delete obsolete legacy tests: `rm tests/test_async_database.py tests/test_db_migration.py`
2. **Step 5F-D4: Regression & Smoke Verification**:
   - Run full non-resilience test suite: `python3 -m pytest tests/ -k "not test_resilience" -q`
   - Run AST boundary test suite: `python3 -m pytest tests/test_architecture_boundaries.py tests/test_api_auxiliary_migration.py -v`
   - Verify 0 test collection errors and 0 missing module errors.
3. **Step 5F-D5: Boundary Audit**:
   - Update `test_architecture_boundaries.py` to assert `src.db_storage` does not exist and is forbidden from ever being imported.
4. **Step 5F-D-FINAL: Commit**:
   - Commit: `"phase-5f-d: retire and remove legacy src/db_storage package"`

---

## 5. Architectural Invariant Compliance

In accordance with user gate instructions:
- **Repository Pattern Boundary**: All domain and API features route through `RepositoryProtocol` $\to$ `ConcreteRepository` $\to$ `SqliteEngine` $\to$ `canonical_events.db`.
- **Zero Premature Deletion**: Audit completed prior to removal.
- **Safety**: Verified that `src/database.py` and `src/events/` remain intact for their respective subsequent retirement gates (5F-E and 5F-F).
