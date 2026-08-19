# Phase 5E Architecture Review & Storage Expansion Specification
**Canonical Article & Source Health Persistence Architecture**

**Author:** Antigravity Principal Systems Architect & Storage Reviewer  
**Date:** 2026-08-14  
**Baseline Git Commit:** `6a762d7` (Phase 5D-C verified & frozen)  
**Cumulative Test Baseline:** `266/266 PASSED`  
**Status:** **APPROVED FOR IMPLEMENTATION**  

---

## 1. Executive Summary & Verdict

Phase 5E expands the canonical persistence layer from the event brain (`TechEvent` aggregates) to encompass **Normalized Articles** (`NormalizedArticle`) and **Source Health Telemetry** (`SourceHealth`). 

```text
                               Canonical Storage Layer (data/canonical_events.db)
                                                      │
              ┌───────────────────────────────────────┼───────────────────────────────────────┐
              ▼                                       ▼                                       ▼
     EventRepository                         ArticleRepository                     SourceHealthRepository
(SqliteEventRepository)                   (SqliteArticleRepository)             (SqliteSourceHealthRepository)
              │                                       │                                       │
              ▼                                       ▼                                       ▼
       canonical_events                       canonical_articles                  canonical_source_health
   canonical_event_sources
   canonical_event_timeline
```

### Architectural Highlights
1. **Single Unified Engine:** All three repositories utilize the shared asynchronous [`SqliteEngine`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_engine.py#L33-L165) under WAL journal mode with connection pooling, transactional atomicity, and busy timeouts.
2. **Domain Contract Invariants:** Ingestion contracts defined in `src/domain/models.py` ([`NormalizedArticle`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L162-L250) and [`SourceHealth`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L674-L804)) remain immutable.
3. **Pipeline Ingestion Boundary:** Clean separation between article ingestion/quality gating (S01–S06), event clustering (S07), and persistence (S10).
4. **Resilience Continuity:** Source health state machine (cooldowns, rate limits, quarantine timers, failure counters) survives daemon restarts.
5. **Zero Legacy Deletion:** Legacy storage (`src/events/`, `src/database.py`, `src/db_storage/`) remains untouched for Phase 5F migration.

**Final Verdict:** **APPROVED FOR IMPLEMENTATION**

---

## 2. Domain Model Audit

### A. NormalizedArticle ([src/domain/models.py:162–250](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L162-L250))

| Field | Type | Storage Representation | Nullable | Description |
| :--- | :--- | :--- | :---: | :--- |
| `id` | `str` | `TEXT PRIMARY KEY` | No | Deterministic hash: `sha256(canonical_url)[:16]` |
| `canonical_url` | `str` | `TEXT UNIQUE` | No | Stripped tracking params, normalized scheme/host |
| `original_url` | `str` | `TEXT` | No | Raw observed URL from source |
| `title` | `str` | `TEXT` | No | Clean Unicode headline |
| `clean_text` | `str` | `TEXT` | No | Plain text article body |
| `summary` | `str` | `TEXT` | No | Summary or excerpt |
| `source_id` | `str` | `TEXT` | No | Stable source registry identifier |
| `source_name` | `str` | `TEXT` | No | Human-readable publisher name |
| `source_tier` | `SourceTier` | `INTEGER` / `TEXT` | No | Quality tier (1=Premium, 2=Specialist, etc.) |
| `zombie_species` | `ZombieSpecies` | `TEXT` | No | Collector species (`z_rss`, `z_github`, etc.) |
| `discovered_at` | `datetime` | `TEXT` (ISO-8601 UTC) | No | UTC timestamp when observed |
| `published_at` | `Optional[datetime]` | `TEXT` (ISO-8601 UTC) | Yes | Authoritative publication timestamp |
| `language` | `str` | `TEXT` | No | ISO 639-1 language code (default `'en'`) |
| `image_url` | `Optional[str]` | `TEXT` | Yes | Hero or thumbnail image URL |
| `authors` | `Tuple[str, ...]` | `TEXT` (JSON Array) | No | List of author strings |
| `tags` | `Tuple[str, ...]` | `TEXT` (JSON Array) | No | Categorization and topic tags |
| `metadata` | `Dict[str, Any]` | `TEXT` (JSON Object) | No | Quality reports, entities, sentiment |

#### Article Lifecycle Rules
- **Identity:** Immutable `id = sha256(canonical_url)[:16]`.
- **Deduplication:** A URL collision constitutes an exact duplicate.
- **Persistence Semantics:** Upsert (`INSERT OR REPLACE` / `INSERT ... ON CONFLICT(id) DO UPDATE`).
- **Relationship to Events:** Referenced by `canonical_event_sources.article_id`.

---

### B. SourceHealth ([src/domain/models.py:674–804](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L674-L804))

| Field | Type | Storage Representation | Nullable | Description |
| :--- | :--- | :--- | :---: | :--- |
| `source_id` | `str` | `TEXT PRIMARY KEY` | No | Stable MD5/SHA256 source hash |
| `source_url` | `str` | `TEXT` | No | Target polling endpoint |
| `source_name` | `str` | `TEXT` | No | Descriptive source name |
| `status` | `SourceHealthStatus` | `TEXT` | No | State machine status (healthy, degraded, cooldown, rate_limited, quarantined, probation, dead) |
| `consecutive_failures` | `int` | `INTEGER` | No | Count of consecutive polling failures |
| `consecutive_successes`| `int` | `INTEGER` | No | Count of consecutive successful fetches |
| `last_attempt` | `Optional[datetime]` | `TEXT` (ISO-8601 UTC) | Yes | Timestamp of most recent poll attempt |
| `last_success` | `Optional[datetime]` | `TEXT` (ISO-8601 UTC) | Yes | Timestamp of most recent successful poll |
| `last_status_code` | `Optional[int]` | `INTEGER` | Yes | HTTP status code from latest attempt |
| `cooldown_until` | `Optional[datetime]` | `TEXT` (ISO-8601 UTC) | Yes | Cooldown or quarantine expiry timestamp |
| `rate_limit_reset_at` | `Optional[datetime]` | `TEXT` (ISO-8601 UTC) | Yes | HTTP 429 rate limit reset timestamp |
| `working_bypass_tier` | `int` | `INTEGER` | No | Effective bypass tier (0=Direct, 1=Browser, etc.) |

#### Source Health Lifecycle Rules
- **Topology:** Single mutable row per source (`source_id` primary key).
- **Restart Continuity:** Telemetry must be read on startup so cooldowns and quarantine periods are preserved across process recycles.
- **Update Frequency:** Updated once per polling cycle per zombie.

---

## 3. SQLite DDL Schema Audit ([src/storage/schema_sqlite.sql](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/schema_sqlite.sql))

### Existing DDL Evaluation

```sql
-- 4. NormalizedArticle Storage Table
CREATE TABLE IF NOT EXISTS canonical_articles (
    id TEXT PRIMARY KEY,                              -- sha256(canonical_url)[:16]
    canonical_url TEXT UNIQUE NOT NULL,
    original_url TEXT NOT NULL,
    title TEXT NOT NULL,
    clean_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_tier TEXT NOT NULL,                        -- Integer or String value
    zombie_species TEXT NOT NULL,
    discovered_at TEXT NOT NULL,                     -- ISO-8601 UTC string
    published_at TEXT,                                -- ISO-8601 UTC string
    language TEXT NOT NULL DEFAULT 'en',
    image_url TEXT,
    authors TEXT NOT NULL DEFAULT '[]',               -- JSON Array
    tags TEXT NOT NULL DEFAULT '[]',                  -- JSON Array
    metadata TEXT NOT NULL DEFAULT '{}',              -- JSON Object
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_canonical_articles_canonical_url ON canonical_articles(canonical_url);
CREATE INDEX IF NOT EXISTS idx_canonical_articles_discovered_at ON canonical_articles(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_articles_source_id ON canonical_articles(source_id);
CREATE INDEX IF NOT EXISTS idx_canonical_articles_published_at ON canonical_articles(published_at DESC);

-- 5. SourceHealth Resilience State Table
CREATE TABLE IF NOT EXISTS canonical_source_health (
    source_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'healthy',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,                                -- ISO-8601 UTC string
    last_success TEXT,                                -- ISO-8601 UTC string
    last_status_code INTEGER,
    cooldown_until TEXT,                              -- ISO-8601 UTC string
    rate_limit_reset_at TEXT,                         -- ISO-8601 UTC string
    working_bypass_tier INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_canonical_source_health_status ON canonical_source_health(status);
```

### DDL Recommendations
- **Index Additions [REQUIRED]:**
  - `idx_canonical_articles_source_id` on `canonical_articles(source_id)` for source-filtered queries.
  - `idx_canonical_articles_published_at` on `canonical_articles(published_at DESC)` for chronological article listings.
  - `idx_canonical_source_health_status` on `canonical_source_health(status)` for rapid discovery of degraded/cooldown sources.
- **Database Placement [REQUIRED]:** Retain tables inside the primary database (`data/canonical_events.db`). Dual-database isolation is unnecessary overhead and complicates transactionality.

---

## 4. Repository Protocols Audit ([src/storage/protocols.py](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/protocols.py))

### A. ArticleRepositoryProtocol

```python
class ArticleRepositoryProtocol(Protocol):
    """Asynchronous repository interface for NormalizedArticle entities."""

    async def save_article(self, article: NormalizedArticle) -> None:
        """Upsert a single NormalizedArticle entity."""
        ...

    async def save_articles(self, articles: Sequence[NormalizedArticle]) -> int:
        """Batch upsert multiple NormalizedArticle entities atomically."""
        ...

    async def get_article(self, article_id: str) -> Optional[NormalizedArticle]:
        """Retrieve a NormalizedArticle by its hash ID."""
        ...

    async def get_article_by_canonical_url(self, canonical_url: str) -> Optional[NormalizedArticle]:
        """Retrieve a NormalizedArticle by its canonical URL."""
        ...

    async def get_recent_articles(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
    ) -> List[NormalizedArticle]:
        """Retrieve recent articles ordered by discovered_at DESC."""
        ...

    async def count_articles(self) -> int:
        """Return the total count of stored canonical articles."""
        ...

    async def delete_article(self, article_id: str) -> bool:
        """Delete an article by ID. Returns True if deleted, False if not found."""
        ...
```

### B. SourceHealthRepositoryProtocol

```python
class SourceHealthRepositoryProtocol(Protocol):
    """Asynchronous repository interface for SourceHealth resilience state."""

    async def save_health(self, health: SourceHealth) -> None:
        """Upsert the resilience state of a data source."""
        ...

    async def save_health_batch(self, health_records: Sequence[SourceHealth]) -> int:
        """Batch upsert source health states atomically."""
        ...

    async def get_health(self, source_id: str) -> Optional[SourceHealth]:
        """Retrieve the resilience state of a specific data source."""
        ...

    async def get_all_health(self) -> List[SourceHealth]:
        """Retrieve all recorded source health states."""
        ...

    async def get_health_by_status(self, status: SourceHealthStatus) -> List[SourceHealth]:
        """Retrieve all source health records with a matching health status."""
        ...
```

---

## 5. Pipeline & Component Integration Points

### A. Article Persistence Point: Post-S06 Quality & Dedup Gate [REQUIRED]
In `CanonicalPipelineRunner.process_observation()`:
```text
S01: Normalization (SourceObservation -> NormalizedArticle)
  ↓
S02: FreshnessEvaluator
  ↓
S03: TechRelevanceFilter
  ↓
S04: QualityGate (Produces QualityReport)
  ↓
S05: DedupEvaluator (Produces DedupDecision)
  ↓
S06: DedupCommitter (Commits to DedupIndex)
  ↓
[PERSIST TO ARTICLE REPOSITORY] ---> await article_repository.save_article(article)
  ↓
S07: EventClusterer (NormalizedArticle -> TechEvent)
  ↓
...
  ↓
S10: PersistenceStage (Persists TechEvent to EventRepository)
```

**Rationale:** Articles should be persisted only after passing quality (S04) and uniqueness (S05/S06) checks, ensuring `canonical_articles` contains high-signal, clean data without storing discarded spam or duplicate payloads.

### B. Source Health Integration Point: ZombieSwarm & SourceRegistry [REQUIRED]
```text
Zombie.hunt() execution
  ├── On Success: health.record_success(working_tier)
  └── On Failure: health.record_failure(status_code, retry_after)
       ↓
await source_health_repo.save_health(health)
```
On daemon startup:
```text
ZombieSwarm.start()
  ↓
await source_health_repo.get_all_health()
  ↓
Hydrate SourceRegistry / Zombie cooldown timers
```

---

## 6. Legacy Storage Consumer Map & Isolation

| Component | File Path | Current Storage Dependency | Phase 5E Plan |
| :--- | :--- | :--- | :--- |
| `Articles API Route` | `src/api/routes/articles.py` | `src.database.Database` | Migrate to `ArticleRepositoryProtocol` in 5E-D |
| `Developer API` | `src/api/main.py` | Legacy memory dicts | Inject `ArticleRepositoryProtocol` in 5E-D |
| `Live Feed Generator`| `src/feed_generator/live_feed.py`| `src.db_storage.db_handler.DatabaseHandler` | Retain untouched until 5F |
| `Legacy Sync Shim` | `src/database.py` | `src.db_storage.unified_storage` | Retain untouched until 5F |
| `Source Monitor` | `src/resilience/source_health.py` | In-memory `SourceHealthMonitor` | Replaced by `SourceHealthRepositoryProtocol` |

---

## 7. Recommendation Classification

| Category | Item | Classification | Rationale |
| :--- | :--- | :--- | :--- |
| **Storage** | Implement `SqliteArticleRepository` | **REQUIRED** | Fulfills canonical article persistence contract |
| **Storage** | Implement `SqliteSourceHealthRepository` | **REQUIRED** | Fulfills source health resilience persistence |
| **Schema** | Add missing indexes to `schema_sqlite.sql` | **REQUIRED** | Optimizes source and timestamp queries |
| **Pipeline** | Wire article persistence into pipeline post-S06 | **REQUIRED** | Stores clean, validated articles |
| **Resilience**| Wire health persistence into Zombie / Registry | **REQUIRED** | Guarantees cooldown persistence across restarts |
| **API** | Migrate `src/api/routes/articles.py` to protocol | **RECOMMENDED** | Eliminates legacy DB dependency in article API |
| **Storage** | Separate SQLite database file for articles | **DANGEROUS** | Causes split-brain locking, cross-DB query barriers |
| **Lifecycle**| Delete legacy `DatabaseHandler` / `Database` | **DANGEROUS** | Must be deferred to Phase 5F |
| **Data** | Migrate old `live_feed.db` rows to canonical | **DEFERRED** | Belongs strictly in Phase 5F migration |

---

## 8. Gated Implementation Plan for Phase 5E

```text
Phase 5E Execution Roadmap:

5E-A: SQLite Article Repository Implementation
  ├── src/storage/sqlite_article_repository.py
  ├── DDL index updates in schema_sqlite.sql
  └── tests/test_sqlite_article_repository.py (Focused unit/roundtrip tests)

5E-B: SQLite Source Health Repository Implementation
  ├── src/storage/sqlite_source_health_repository.py
  └── tests/test_sqlite_source_health_repository.py (Focused state machine persistence tests)

5E-C: Pipeline Article Persistence Integration
  ├── Wire ArticleRepositoryProtocol into CanonicalPipelineRunner (post-S06)
  └── tests/test_pipeline_article_persistence.py

5E-D: Source Health & Swarm Lifecycle Integration
  ├── Wire SourceHealthRepositoryProtocol into Zombie / SourceRegistry
  └── tests/test_source_health_lifecycle.py

5E-E: API Article Router Migration
  ├── Migrate src/api/routes/articles.py to ArticleRepositoryProtocol
  └── tests/test_api_articles_migration.py

5E-F: Cross-Boundary Integration & Phase 5E Closeout
  ├── Full multi-process restart verification (Articles + Health + Events)
  ├── PHASE_5E_IMPLEMENTATION_REPORT.md
  └── Full test suite regression (266 + new tests)
```

---

## 9. Acceptance Criteria for Phase 5E

1. **Zero Domain Model Drift:** `NormalizedArticle` and `SourceHealth` models in `src/domain/models.py` remain unchanged.
2. **Deterministic CRUD Operations:** Full roundtrip persistence tests verify exact field serialization, UTC normalization, and JSON encoding.
3. **Pipeline Ingestion Integrity:** Valid articles are saved to `canonical_articles`; rejected/duplicate articles are not persisted.
4. **Resilience State Continuity:** Quarantines, cooldowns, and rate limits survive cold restart simulations.
5. **AST Boundary Purity:** Zero imports of `sqlite3`, `aiosqlite`, or raw SQL in pipeline stages or API routers.
6. **Cumulative Regression:** All 266 existing tests continue to pass without regression.
7. **Legacy Retention:** `src/events/`, `src/database.py`, and `src/db_storage/` remain intact for Phase 5F.

---

**Architecture Review Complete.** Ready to proceed with gated subphases upon your direction.
