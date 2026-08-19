# Phase 5F-F Architecture Review: Legacy `src/database.py` and `src/scraper.py` Retirement

**Milestone**: Subphase 5F-F (5F-F1 Architecture Review)  
**Status**: AUDIT COMPLETE — AWAITING GATE AUTHORIZATION  
**Target Files**: `src/database.py` (120 lines), `src/scraper.py` (995 lines)  
**Git Baseline**: `83ce434` (Subphase 5F-E committed; clean working tree)  
**Baseline Test Suite**: 162/162 core canonical tests passing  

---

## 1. Executive Summary

Subphase **5F-F** is the final decommissioning gate for Phase 5 legacy storage infrastructure. It targets the two remaining legacy root modules in `src/`:
1. `src/database.py`: The Phase 0 synchronous in-memory database shim (`LegacyDatabaseShim`, `get_database()`, `Database`).
2. `src/scraper.py`: The Phase 0 monolithic scraper orchestrator (`TechNewsScraper`).

In Phases 1 through 5:
- **Acquisition**: Replaced by **`ZombieSwarm`** (`ZRss`, `ZWeb`, `ZCorp`, `ZHacker`, `ZGitHub`, `ZSecurity`) and **`ScraperFactory`**, emitting immutable, validated `SourceObservation` domain contracts.
- **Pipeline Processing**: Structured into the 11-stage **`CanonicalPipelineRunner`** (S01 through S11).
- **Persistence**: Consolidated onto **`SqliteEngine`** (`canonical_events.db`) via specialized repositories (`SqliteArticleRepository`, `SqliteEventRepository`, `SqliteSourceHealthRepository`, `SqliteUserPreferencesRepository`).

```
                    CANONICAL PRODUCTION ARCHITECTURE
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
               ZombieSwarm                   ScraperFactory
         (ZRss, ZWeb, ZCorp, ...)        (Direct Feed Acquisition)
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
                            SourceObservation
                                    │
                                    ▼
                         CanonicalPipelineRunner
                              (Stages S01-S11)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                 Articles        Events       Source Health
                    │               │               │
                    ▼               ▼               ▼
               SqliteArticle   SqliteEvent    SqliteSourceHealth
                 Repository      Repository       Repository
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                         SqliteEngine (WAL mode)
                                    │
                                    ▼
                           canonical_events.db

       =========================================================
       DECOMMISSION TARGET IN 5F-F:
         ✗ src/database.py  (120 lines) — PERMANENT DELETION
         ✗ src/scraper.py   (995 lines) — PERMANENT DELETION
         ✗ tests/test_database.py       — PERMANENT DELETION
         ✗ tests/test_scraper.py        — PERMANENT DELETION
       =========================================================
```

---

## 2. Deep Audit: `src/database.py` (11 Storage Dimensions)

`src/database.py` (120 lines) defines `LegacyDatabaseShim`, `get_database()`, and `Database`. It holds in-memory Python structures (`self.articles`, `self.url_cache`, `self.discovered_sources`).

### 11-Dimension Storage Operation Mapping

| # | Storage Dimension | Legacy Operation in `src/database.py` | Canonical Replacement | Migration Status | Safe to Delete? |
|---|---|---|---|---|---|
| 1 | **Articles** | `save_articles()`, `save_article()`, `add_article()`, `get_all_articles()`, `get_article_count()` | `SqliteArticleRepository` (`save_articles_batch`, `save_article`, `get_article_by_id`, `get_article_count`, `get_recent_articles`) | **100% Migrated** | **YES** |
| 2 | **Events** | None (Previously in `src/events/`) | `SqliteEventRepository` on `canonical_events.db` | **100% Migrated** | **YES** |
| 3 | **Sources** | `add_discovered_source()`, `get_source_count()`, `discovered_sources` | `SqliteSourceHealthRepository` (`upsert_source`, `get_source_health`, `get_all_health`) | **100% Migrated** | **YES** |
| 4 | **Preferences** | None (Previously in `db_storage/`) | `SqliteUserPreferencesRepository` (`get_preferences`, `save_preferences`, `record_reading_history`, `add_bookmark`) | **100% Migrated** | **YES** |
| 5 | **Search** | `search_articles(query, limit)` (in-memory substring) | `SqliteArticleRepository.search_articles()` (parameterized SQL + FTS5) | **100% Migrated** | **YES** |
| 6 | **Retention** | None (unbounded in-memory list) | `SqliteArticleRepository.enforce_retention_policy(cutoff)` + `SqliteEngine` table cleanup | **100% Migrated** | **YES** |
| 7 | **Sentiment** | None (handled in memory) | `SqliteArticleRepository` sentiment metadata fields + API aggregates | **100% Migrated** | **YES** |
| 8 | **Configuration** | `db_path = DB_FILE` | `config.settings.DB_FILE` and `SqliteEngine(db_path)` | **100% Migrated** | **YES** |
| 9 | **Statistics** | `get_article_count()`, `get_source_count()` | `SqliteArticleRepository.get_article_count()`, `SqliteSourceHealthRepository.get_all_health()` | **100% Migrated** | **YES** |
| 10 | **Cleanup** | `clear_session_data()` (`self.articles.clear()`) | GUI in-memory list management / `SqliteEngine` | **100% Migrated** | **YES** |
| 11 | **Transactions** | `_run_async()` wrapper (no true transaction) | `SqliteEngine.transaction()` context manager (ACID atomic commit/rollback) | **100% Migrated** | **YES** |

---

## 3. Deep Audit: `src/scraper.py`

### Classification: **Category A — Completely Obsolete**

`src/scraper.py` (995 lines) was the Phase 0 prototype `TechNewsScraper`.

### Architectural Comparison: Legacy vs Modern Acquisition Path

```
LEGACY PATH (src/scraper.py):
  Internet ──▶ TechNewsScraper (monolithic) ──▶ Dict ──▶ Database.save_articles() (in-memory)

MODERN CANONICAL PATH:
  Internet ──▶ ZombieSwarm (ZRss, ZWeb, ZCorp, ZHacker, ZGitHub, ZSecurity)
                  │
                  ▼
          SourceObservation (immutable domain value object)
                  │
                  ▼
          CanonicalPipelineRunner (S01-S11: normalizer, dedup, quality, scoring, clustering)
                  │
                  ▼
          SqliteArticleRepository & SqliteEventRepository (durable SQLite WAL)
```

| Dimension | Legacy `TechNewsScraper` (`src/scraper.py`) | Modern Production System |
|---|---|---|
| **Orchestration** | Monolithic `TechNewsScraper` loop | `ZombieSwarm` with distributed worker concurrency |
| **Species Specialization** | Ad-hoc branching | Dedicated zombie classes (`ZRss`, `ZWeb`, `ZCorp`, `ZHacker`, `ZGitHub`, `ZSecurity`) |
| **Data Contract** | Raw unvalidated dictionaries | Validated, immutable `SourceObservation` domain contracts |
| **Pipeline Integration** | Synchronous parsing + direct insertion | 11-stage canonical pipeline (`CanonicalPipelineRunner` S01-S11) |
| **Bypass & Anti-Bot** | Embedded `try/except` in `src/scraper.py` | Modular plugins in `src/bypass/` and `src/scrapers/` |
| **Persistence** | Direct `Database.save_articles()` | Clean repository protocols on `SqliteEngine` |

`src/scraper.py` contributes **zero unique logic or behavior** not already superseded by the modern pipeline.

---

## 4. Comprehensive Dependency Closure Audit

### 1. Production Source Code (`src/`)
- `src/scraper.py`: Imports `from src.database import Database` (both deleted concurrently in 5F-F3).
- `src/monitoring/logging_configuration.py`: Contains obsolete logger key `"src.scraper": "INFO"` (cleaned in 5F-F2).
- **All other `src/` modules**: **ZERO imports** of `src.database` or `src.scraper`.

### 2. Runtime Entrypoints & Daemons
- `main.py`: Uses `SqliteEngine`, `SqliteArticleRepository`, `ScraperFactory`. (0 legacy imports).
- `main_engine.py`: Uses `CyclicSourceScheduler`, `DedupGate`, `FeedChain`. (0 legacy imports).
- `cli.py`: Uses `TechNewsOrchestrator`. (0 legacy imports).
- `telegram_feeder_bot.py`: Uses SSE and HTTP streaming client. (0 legacy imports).

### 3. GUI Modules (`gui_qt/`)
- `gui_qt/app_qt_migrated.py`: Contains 4 lazy fallback calls to `get_database()` (cleaned in 5F-F2 to use UI list state).
- `gui_qt/panels/admin_panel.py`: 1 lazy fallback `get_database().get_article_count()` (cleaned in 5F-F2).
- `gui_qt/dialogs/disruptive_news_dialog.py`: 1 lazy fallback `get_database().get_disruptive_articles()` (cleaned in 5F-F2).

### 4. Scripts (`scripts/`)
- `scripts/migrate_db.py`: Imports `DB_FILE` from `src.database` (switched to `config.settings` in 5F-F2).

### 5. Test Suite (`tests/`)
- `tests/test_database.py`: Legacy tests for `src/database.py` (deleted in 5F-F3).
- `tests/test_scraper.py`: Legacy tests for `src/scraper.py` (deleted in 5F-F3).
- `tests/test_integration_bypass.py`: 1 method testing `TechNewsScraper` (modernized in 5F-F2).
- `tests/test_discovery.py` & `tests/test_user_preferences.py`: Test fixtures with `Database` mock (cleaned in 5F-F2).

---

## 5. Subphase 5F-F Execution Plan

### Step 5F-F1: Architecture & Dependency Review (Current Step)
- Audit all operations across 11 storage dimensions.
- Confirm complete obsolescence of `src/database.py` and `src/scraper.py`.

### Step 5F-F2: Consumer Decoupling & Modernization
1. In `gui_qt/app_qt_migrated.py`: Remove 4 lazy `get_database()` fallbacks.
2. In `gui_qt/panels/admin_panel.py`: Clean `get_database()` fallback.
3. In `gui_qt/dialogs/disruptive_news_dialog.py`: Clean `get_database()` fallback.
4. In `scripts/migrate_db.py`: Import `DB_FILE` from `config.settings`.
5. In `tests/test_integration_bypass.py`: Update test to verify `ContentPlatformBypass` with `EnhancedWebCrawler`.
6. In `tests/test_discovery.py` & `tests/test_user_preferences.py`: Decouple test fixtures from `Database`.
7. In `src/monitoring/logging_configuration.py`: Remove obsolete `"src.scraper"` key.

### **Gate F-A Verification**: Run targeted decoupling tests before deletion.

### Step 5F-F3: Physical Deletion of Legacy Modules
1. Delete `src/database.py`
2. Delete `src/scraper.py`
3. Delete `tests/test_database.py`
4. Delete `tests/test_scraper.py`

### Step 5F-F4: Permanent Architecture Invariant Hardening
Add `TestLegacyModulesArchitectureBoundaries` to `tests/test_architecture_boundaries.py`:
- Invariant: `src/database.py` and `src/scraper.py` must never exist on disk.
- Invariant: Zero `.py` files in `src/`, `gui_qt/`, or root entrypoints may import `src.database` or `src.scraper`.
- Invariant: Zero `.py` files in `src/` may instantiate `LegacyDatabaseShim` or `TechNewsScraper`.

### Step 5F-F5: Full Multi-Gate Verification
- **Gate A**: Architecture boundaries & targeted migration tests.
- **Gate B**: Canonical storage tests (162/162).
- **Gate C**: Complete regression suite.
- **Gate D**: Compileall & import smoke tests.

### Step 5F-F6: Implementation Report & Milestone Commit
- Author `PHASE_5F_F_IMPLEMENTATION_REPORT.md`.
- Commit with message: `"phase-5f-f: retire and remove legacy database and scraper modules"`.
- Maintain zero GitHub push invariant.

---

## 6. Safety & Boundary Invariants

- **Non-Destructive for Modern Components**: Modern acquisition (`ZombieSwarm`, `ScraperFactory`) and canonical storage repositories (`SqliteArticleRepository`, `SqliteEventRepository`, `SqliteSourceHealthRepository`, `SqliteUserPreferencesRepository`) remain untouched.
- **Test Integrity**: Full regression suite must pass with 0 collection or runtime errors.
- **Zero Drift**: No intermediate state with broken imports or half-deleted modules.
