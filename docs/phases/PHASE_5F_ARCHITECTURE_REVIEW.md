# Phase 5F Architecture Review: Legacy Storage Migration & Retirement

**Document Version:** 1.0.0  
**Author:** Antigravity Principal Systems Architect & Storage Migration Lead  
**Date:** 2026-08-15  
**Baseline Git Commit:** `54e271f` (Phase 5 Audit Complete & Committed)  
**Cumulative Test Baseline:** `339/339 PASSED`  
**Status:** **APPROVED FOR IMPLEMENTATION PLANNING**  

---

## 1. Executive Summary & Objective

Phase 5F is the final closure phase of the Phase 5 storage modernization. Its mission is to migrate all remaining auxiliary consumers from legacy storage wrappers ([`src/database.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/database.py), `src/db_storage/`, and `src/events/`) to the canonical SQLite storage engine ([`SqliteEngine`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_engine.py#L33)), and subsequently delete all obsolete legacy storage code.

```text
                                LEGACY STORAGE RETIREMENT
                                           │
          ┌────────────────────────────────┼────────────────────────────────┐
          ▼                                ▼                                ▼
    src/database.py                  src/db_storage/                   src/events/
(Sync SQLite Wrapper)            (Legacy Unified Storage)          (Legacy EventStore)
          │                                │                                │
          └────────────────────────────────┼────────────────────────────────┘
                                           │
                                  MIGRATE CONSUMERS
                                           │
                 ┌─────────────────────────┴─────────────────────────┐
                 ▼                                                   ▼
     Canonical Core Repositories                         Specialized Aux Repositories
(ArticleRepo, EventRepo, HealthRepo)                (UserPreferencesRepo, Search, etc.)
                 │                                                   │
                 └─────────────────────────┬─────────────────────────┘
                                           ▼
                                  Shared SqliteEngine
                                           ▼
                                data/canonical_events.db
                                           │
                                           ▼
                                 DELETE LEGACY CODE
```

---

## 2. Comprehensive Legacy Storage Inventory & Destination Matrix

Our deep codebase audit identified every remaining consumer of legacy storage abstractions and established its exact destination:

| Legacy Component | Consumer Module | Stored Entities / Operations | Destination Architecture | Phase 5F Action |
| :--- | :--- | :--- | :--- | :--- |
| `src/database.py` | `src/api/routes/search.py` | Full-text article search | `ArticleRepositoryProtocol.search_articles()` on `canonical_articles` | **Migrate** |
| `src/database.py` | `src/api/routes/sentiment.py` | Article lookup for on-demand NLP | `ArticleRepositoryProtocol.get_article()` on `canonical_articles` | **Migrate** |
| `src/database.py` | `src/api/main.py` | Health counts, article search/listing | Mount canonical `articles_router`, `events_router`, `search_router` | **Migrate** |
| `src/database.py` | `src/user/preferences.py` | User topics, sources, bookmarks | `SqliteUserPreferencesRepository` on `SqliteEngine` | **Migrate** |
| `src/database.py` | `src/compliance/data_privacy_manager.py` | User data cleanup & GDPR deletion | Parameterized deletion on `SqliteEngine` | **Migrate** |
| `src/database.py` | `src/monitoring/health_check_endpoints.py` | Article count & DB connectivity check | `ArticleRepositoryProtocol.count_articles()` on `SqliteEngine` | **Migrate** |
| `src/database.py` | `src/operations/diagnostic_toolkit.py` | Article & source diagnostics | Repositories on `SqliteEngine` | **Migrate** |
| `src/database.py` | `src/queue/tasks.py` | Celery article retention cleanup | `ArticleRepositoryProtocol.delete_old_articles()` | **Migrate** |
| `src/database.py` | `src/discovery/__init__.py`, `src/discovery.py` | Discovered target source URLs | `SourceRegistry` / `SourceHealthRepositoryProtocol` | **Migrate** |
| `src/database.py` | `src/scraper.py` | Legacy sync scraper article writes | Superseded by `ZombieSwarm` + Canonical Pipeline | **Retire** |
| `src/db_storage/` | `src/api/app.py` | `db_handler = DatabaseHandler()` | Remove `db_handler` (fully replaced by `SqliteEngine`) | **Retire & Delete** |
| `src/db_storage/` | `src/engine/orchestrator.py` | Legacy feed orchestration | Superseded by `UnifiedFeedChainEngine` | **Retire** |
| `src/events/` | `src/api/routes/events.py` (legacy type hint) | In-memory `EventStore` | Replaced by `SqliteEventRepository` | **Delete** |

---

## 3. Specialized Auxiliary Repository Design (Avoiding GodRepository)

To maintain clean single-responsibility boundaries and avoid turning `ArticleRepository` into a "God Repository", responsibilities are segmented into clear domain-specific contracts:

### A. Article Search & Retention (`ArticleRepositoryProtocol` Extensions)
In [`src/storage/protocols.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/protocols.py#L84):
- Add `search_articles(query: str, limit: int = 20, offset: int = 0) -> List[NormalizedArticle]`
- Add `delete_articles_older_than(cutoff: datetime) -> int`

Implemented in [`SqliteArticleRepository`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_article_repository.py#L73) via parameterized SQL queries on `canonical_articles`.

### B. User Preferences & Personalization Repository
Create dedicated protocol and implementation in `src/storage/`:
- Protocol: `UserPreferencesRepositoryProtocol` in `src/storage/protocols.py`
  - `get_preferences(user_id: str) -> Optional[UserPreferences]`
  - `save_preferences(preferences: UserPreferences) -> None`
  - `get_user_bookmarks(user_id: str) -> List[Dict[str, Any]]`
  - `delete_user_data(user_id: str) -> Dict[str, int]`
- Implementation: `SqliteUserPreferencesRepository` utilizing `SqliteEngine` for tables `user_preferences`, `user_topics`, `user_sources`, `user_bookmarks`.

---

## 4. Phase 5F Subphase Gating & Roadmap

Phase 5F will be executed under strict subphase gating with regression testing at every step:

```text
5F-A  Legacy Storage Architecture Review (This Document)             APPROVED ✅
  │
  ▼
5F-B  Auxiliary Repository & Protocol Design (Search, Preferences)    ⏭ READY
  │
  ▼
5F-C  Auxiliary Consumer Migration (Search, Sentiment, Main, etc.)    ⏭ QUEUED
  │
  ▼
5F-D  Retirement & Removal of src/db_storage/                         ⏭ QUEUED
  │
  ▼
5F-E  Retirement & Removal of src/events/ (Legacy EventStore)         ⏭ QUEUED
  │
  ▼
5F-F  Retirement & Removal of src/database.py & src/scraper.py        ⏭ QUEUED
  │
  ▼
5F-G  Full System Cross-Boundary Regression, Concurrency & AST Audit  ⏭ QUEUED
  │
  ▼
5F-H  Phase 5 Final Freeze & Comprehensive Architecture Closeout      ⏭ QUEUED
```

### Detailed Subphase Breakdown:

1. **Subphase 5F-B: Auxiliary Repository & Protocol Design**
   - Add `search_articles` and `delete_articles_older_than` to `ArticleRepositoryProtocol` and `SqliteArticleRepository`.
   - Add `UserPreferencesRepositoryProtocol` and `SqliteUserPreferencesRepository`.
   - Update `schema_sqlite.sql` with user preference tables.
   - Comprehensive unit tests in `tests/test_sqlite_auxiliary_repositories.py`.

2. **Subphase 5F-C: Auxiliary Consumer Migration**
   - Migrate `src/api/routes/search.py` to `ArticleRepositoryProtocol.search_articles()`.
   - Migrate `src/api/routes/sentiment.py` to `ArticleRepositoryProtocol.get_article()`.
   - Migrate `src/api/main.py` to use canonical routers and repositories.
   - Migrate `src/user/preferences.py` and `src/compliance/data_privacy_manager.py` to `UserPreferencesRepositoryProtocol` and `SqliteEngine`.
   - Migrate `src/monitoring/health_check_endpoints.py` and `src/operations/diagnostic_toolkit.py`.
   - Migrate `src/queue/tasks.py`.

3. **Subphase 5F-D: `src/db_storage/` Retirement & Removal**
   - Remove `db_handler` from `src/api/app.py` lifespan.
   - Verify zero remaining consumers of `src/db_storage/`.
   - Safely delete `src/db_storage/`.

4. **Subphase 5F-E: `src/events/` Retirement & Removal**
   - Verify zero remaining consumers of `src/events/event_store.py` and `src/events/event_types.py`.
   - Safely delete `src/events/`.

5. **Subphase 5F-F: `src/database.py` & `src/scraper.py` Retirement & Removal**
   - Verify zero remaining imports of `src.database` across entire codebase.
   - Safely delete `src/database.py` and obsolete `src/scraper.py`.

6. **Subphase 5F-G: Full System Regression, Concurrency & AST Audit**
   - Run AST audit asserting **0 occurrences** of legacy storage across the repository.
   - Run full cumulative test suite across all subsystems.

7. **Subphase 5F-H: Phase 5 Final Freeze**
   - Generate `PHASE_5F_IMPLEMENTATION_REPORT.md` and complete immutable Phase 5 freeze.

---

## 5. Non-Regressive Invariants & Rules

1. **No Destructive Deletion Before Migration:** No legacy file will be deleted until all consumers have been refactored, tested, and verified.
2. **Protocol Decoupling:** All new features/repos must strictly follow the protocol inversion pattern.
3. **Single Database Invariant:** All persistent tables live in `data/canonical_events.db` via `SqliteEngine`.
4. **Cumulative Test Green Invariant:** All 339 existing tests must remain passing throughout every 5F subphase.

---

**Architecture Review Complete.** Ready to authorize **Subphase 5F-B (Auxiliary Repository & Protocol Design)**.
