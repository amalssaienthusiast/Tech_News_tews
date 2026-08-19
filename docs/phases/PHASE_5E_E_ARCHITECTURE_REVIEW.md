# Phase 5E-E Architecture Review: API Article Migration

**Document Version:** 1.0.0  
**Author:** Antigravity Principal Systems Architect & Storage Reviewer  
**Date:** 2026-08-15  
**Baseline Git Commit:** `474bebb` (Subphases 5E-A through 5E-D committed & clean)  
**Cumulative Test Baseline:** `325/325 PASSED`  
**Status:** **APPROVED FOR IMPLEMENTATION**  

---

## 1. Executive Summary & Objective

Subphase 5E-E completes the migration of the articles API surface ([`src/api/routes/articles.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/routes/articles.py)) from the legacy synchronous [`src.database.Database`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/database.py) to the canonical asynchronous [`ArticleRepositoryProtocol`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/protocols.py#L84-L136) (backed by [`SqliteArticleRepository`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_article_repository.py#L73-L324)).

```text
                  FastAPI Application (src/api/app.py)
                                  │
                       Lifespan Startup / Engine
                                  │
                                  ▼
                     SqliteArticleRepository
                                  │
                                  ▼
                     set_article_repository(repo)
                                  │
                   ┌──────────────┴──────────────┐
                   ▼                             ▼
         GET /v1/articles              GET /v1/articles/{id}
  (Pagination, Source Filter)         (ID & Canonical URL Lookup)
                   │                             │
                   ▼                             ▼
        ArticleRepositoryProtocol      ArticleRepositoryProtocol
                   │                             │
                   ▼                             ▼
         canonical_articles           canonical_articles
      (data/canonical_events.db)    (data/canonical_events.db)
```

**Final Verdict:** **APPROVED FOR IMPLEMENTATION**

---

## 2. Current State vs. Target Architecture

### A. Current Implementation Flaws ([`src/api/routes/articles.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/routes/articles.py))
1. **Direct Legacy Database Coupling:** Instantiates `db = Database()` from `src.database` inside route handlers, blocking the async event loop with synchronous file/memory operations.
2. **Missing Dependency Injection:** Lacks standard FastAPI `Depends()` injection and repository setters/getters.
3. **Unnormalized DTO Mapping:** Assumes loose dictionaries (`a.get("source")`, `a.get("ai_summary")`) instead of type-safe canonical [`NormalizedArticle`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L198) domain entities.
4. **App Lifespan Disconnect:** [`src/api/app.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/app.py) mounts `events_router` with `SqliteEventRepository`, but does not mount `articles_router` or initialize `SqliteArticleRepository`.

### B. Target Architecture (Phase 5E-E)
1. **Pure Protocol Dependency:** Route handlers depend strictly on [`ArticleRepositoryProtocol`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/protocols.py#L84-L136) via `Depends(get_article_repository)`.
2. **FastAPI Lifespan Integration:** Initialized in [`src/api/app.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/app.py) sharing the existing `SqliteEngine` instance on startup; released on shutdown.
3. **Domain-to-DTO Mapping:** Replaces ad-hoc dictionary lookups with `ArticleResponse.from_domain(article: NormalizedArticle)`.
4. **Resilient Lookup:** Supports lookup by both 16-character hash `id` and `canonical_url` with 404 fallback.
5. **Zero Direct SQLite Imports:** Zero imports of `sqlite3`, `aiosqlite`, or `SqliteArticleRepository` inside `src/api/routes/articles.py`.

---

## 3. Detailed Component Design & API Contract

### A. Route Dependency Injection Pattern
```python
# src/api/routes/articles.py

_shared_repository: Optional[ArticleRepositoryProtocol] = None

def get_article_repository() -> ArticleRepositoryProtocol:
    """Resolve active ArticleRepositoryProtocol or raise RuntimeError if uninitialized."""
    global _shared_repository
    if _shared_repository is None:
        raise RuntimeError(
            "ArticleRepository has not been initialized. "
            "Call set_article_repository(repo) during application startup."
        )
    return _shared_repository

def set_article_repository(repository: Optional[ArticleRepositoryProtocol]) -> None:
    """Inject the canonical ArticleRepositoryProtocol instance."""
    global _shared_repository
    _shared_repository = repository
```

### B. Endpoint Specifications

#### 1. `GET /v1/articles`
- **Query Parameters:**
  - `page: int = Query(1, ge=1)`
  - `per_page: int = Query(20, ge=1, le=100)`
  - `source: Optional[str] = Query(None, description="Filter by source_id")`
- **Execution Flow:**
  - `offset = (page - 1) * per_page`
  - `articles = await repo.get_recent_articles(limit=per_page, offset=offset, source_id=source)`
  - `total = await repo.count_articles()`
  - `has_more = (offset + len(articles)) < total`
- **Response Model:** `ArticlesListResponse`

#### 2. `GET /v1/articles/{article_id}`
- **Path Parameter:** `article_id: str`
- **Execution Flow:**
  - `article = await repo.get_article(article_id)`
  - `if article is None: article = await repo.get_article_by_canonical_url(article_id)`
  - `if article is None: raise HTTPException(status_code=404, detail="Article not found")`
- **Response Model:** `ArticleResponse`

### C. DTO Serialization Fidelity (`ArticleResponse.from_domain`)
```python
@classmethod
def from_domain(cls, article: NormalizedArticle) -> ArticleResponse:
    return cls(
        id=article.id,
        title=article.title,
        url=article.canonical_url,
        source=article.source_name or article.source_id,
        published_at=article.published_at.isoformat() if article.published_at else None,
        summary=article.summary or (article.clean_text[:300] if article.clean_text else None),
        sentiment_score=article.metadata.get("sentiment_score") if isinstance(article.metadata, dict) else None,
        topics=list(article.tags or ()),
    )
```

---

## 4. Lifespan Integration in `src/api/app.py`

```python
# Startup in lifespan(app: FastAPI):
canonical_article_repo = SqliteArticleRepository(engine=canonical_engine, auto_init=True)
set_article_repository(canonical_article_repo)
app.state.canonical_article_repository = canonical_article_repo

# Mounting routes:
app.include_router(articles_router)

# Shutdown in lifespan(app: FastAPI):
set_article_repository(None)
```

---

## 5. Scope & Boundary Rules

### Files Proposed for Modification:
1. [`src/api/routes/articles.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/routes/articles.py) (Full migration to `ArticleRepositoryProtocol`)
2. [`src/api/app.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/app.py) (Mount `articles_router`, wire `SqliteArticleRepository` in lifespan)
3. [`tests/test_api_articles_migration.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/tests/test_api_articles_migration.py) (Comprehensive test suite)
4. [`PHASE_5E_E_IMPLEMENTATION_REPORT.md`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/PHASE_5E_E_IMPLEMENTATION_REPORT.md) (Closeout documentation)

### Files Explicitly FORBIDDEN from Modification:
- `src/domain/models.py` (Domain models frozen)
- `src/domain/enums.py` (Domain enums frozen)
- `src/storage/schema_sqlite.sql` (Schema DDL frozen)
- `src/storage/sqlite_*` (Repositories frozen)
- `src/pipeline/*` (Pipeline runner/stages frozen)
- `src/zombies/*` (Acquisition frozen)
- `src/database.py`, `src/db_storage/`, `src/events/` (Legacy storage frozen for 5F)

---

## 6. Test Strategy for Subphase 5E-E

`tests/test_api_articles_migration.py` will verify:
1. **Repository Injection:** `set_article_repository` / `get_article_repository` functioning as expected.
2. **List Pagination:** `GET /v1/articles?page=1&per_page=10` correct slicing and pagination metadata.
3. **Source Filtering:** `GET /v1/articles?source=techcrunch` filters by `source_id`.
4. **Single Article Lookup (ID):** `GET /v1/articles/{id}` returns 200 with complete DTO mapping.
5. **Single Article Lookup (Canonical URL):** Fallback URL lookup returns 200.
6. **404 Not Found:** Non-existent ID returns clean 404 response.
7. **Authentication:** Request without valid API key returns 401.
8. **App Lifespan Integration:** End-to-end FastAPI test client with real `SqliteArticleRepository` on SQLite.
9. **AST Boundary Purity:** Zero imports of `sqlite3`, `aiosqlite`, or `SqliteArticleRepository` in `src/api/routes/articles.py`.

---

## 7. Acceptance Criteria for Subphase 5E-E

1. **Clean Protocol Boundary:** `articles.py` imports only `ArticleRepositoryProtocol`.
2. **Lifespan Initialization:** Real application startup initializes and injects `SqliteArticleRepository`.
3. **Zero Regressions:** 325 existing tests + all new 5E-E tests pass (100% passing).
4. **Clean Git State:** Zero lint errors, zero unauthorized file edits, zero git pushes.

---

**Architecture Review Complete.** Ready for implementation upon your approval.
