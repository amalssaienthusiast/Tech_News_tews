# Phase 6C Architecture Review: SQLite FTS5 Full-Text Search Integration

**Program**: Phase 6 — Internet-Scale Acquisition, Search, Security & Production Operations  
**Gate**: Gate 6C-A (Full-Text Search Architecture Review)  
**Status**: SUBMITTED FOR REVIEW & AUTHORIZATION  
**Baseline Commit**: `285c03d` (Phase 6B Frozen)  
**Code Modifications in 6C-A**: 0 (Architecture & Design Review Only)  

---

## 1. Executive Summary & Design Invariants

Subphase **6C** integrates high-performance lexical search directly into the canonical storage layer using native SQLite **FTS5** full-text indexing, BM25 relevance scoring, and contextual snippet extraction.

### Core Architectural Invariants:
1. **Derived Index Invariant**: `canonical_articles` is the **single authoritative source of truth**. `canonical_articles_fts` is strictly a derived, synchronized search index.
2. **Protocol Boundary Invariant**: API route `/api/v1/articles/search` depends exclusively on `ArticleRepositoryProtocol.search_articles_fts()`. No raw SQL, virtual table names, or SQLite drivers exist in the API layer.
3. **Transaction Atomicity**: All FTS5 index updates synchronize automatically within the same atomic transaction as `canonical_articles` mutations via SQLite triggers.

```
                         HTTP Search Request
                        GET /api/v1/articles/search?q=...
                                │
                                ▼
                    ArticleRepositoryProtocol
                                │
                                ▼
                     SqliteArticleRepository
                                │
                   FTS5 BM25 Ranked Search Query
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
    canonical_articles_fts               canonical_articles
    (BM25 Score + Snippets)              (Authoritative Domain Entities)
              │                                   │
              └─────────────────┬─────────────────┘
                                ▼
                       List[ArticleSearchResult]
                                │
                                ▼
                      JSON Response + Pagination
```

---

## 2. FTS5 Virtual Table Schema & Tokenizer Design

### 1. Table Schema
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS canonical_articles_fts USING fts5(
    id UNINDEXED,
    title,
    clean_text,
    summary,
    tags,
    tokenize = 'unicode61 remove_diacritics 2'
);
```

### 2. Tokenizer Decision: `unicode61`
- **Case-Insensitive & Diacritic-Insensitive**: Supports multi-lingual tech news queries (e.g. `résumé` matches `resume`).
- **Punctuation Stripping**: Handles hyphens, slashes, and camelCase naturally.

---

## 3. Trigger-Based Automatic Synchronization

Three SQLite triggers guarantee that `canonical_articles_fts` never drifts from `canonical_articles`:

```sql
-- 1. Insert Trigger
CREATE TRIGGER IF NOT EXISTS trg_canonical_articles_fts_insert
AFTER INSERT ON canonical_articles
BEGIN
    INSERT INTO canonical_articles_fts(id, title, clean_text, summary, tags)
    VALUES (new.id, new.title, new.clean_text, new.summary, new.tags);
END;

-- 2. Delete Trigger
CREATE TRIGGER IF NOT EXISTS trg_canonical_articles_fts_delete
AFTER DELETE ON canonical_articles
BEGIN
    DELETE FROM canonical_articles_fts WHERE id = old.id;
END;

-- 3. Update Trigger
CREATE TRIGGER IF NOT EXISTS trg_canonical_articles_fts_update
AFTER UPDATE ON canonical_articles
BEGIN
    DELETE FROM canonical_articles_fts WHERE id = old.id;
    INSERT INTO canonical_articles_fts(id, title, clean_text, summary, tags)
    VALUES (new.id, new.title, new.clean_text, new.summary, new.tags);
END;
```

---

## 4. Idempotent Migration & Startup Backfill

On engine startup (`SqliteEngine.initialize_schema()`), the schema DDL is executed. To handle existing databases seamlessly, an idempotent backfill statement populates any unindexed articles:

```sql
INSERT OR IGNORE INTO canonical_articles_fts(id, title, clean_text, summary, tags)
SELECT id, title, clean_text, summary, tags
FROM canonical_articles
WHERE id NOT IN (SELECT id FROM canonical_articles_fts);
```

---

## 5. Query Sanitization & Injection Defense

FTS5 query syntax treats certain punctuation and keywords as operators (`"`, `*`, `^`, `NEAR`, `AND`, `OR`, `NOT`, `:`, `-`). Unsanitized user inputs can trigger SQLite syntax errors (`fts5: syntax error near ...`).

### Query Sanitizer Strategy (`src/storage/fts_sanitizer.py`):
1. **Clean Whitespace & Control Characters**: Trim and normalize whitespace.
2. **Safe Tokenization**: Extract alphanumeric terms and quoted phrases.
3. **Prefix Support**: Automatically append `*` to trailing query terms for interactive autocomplete search (e.g. `artif* intel*`).
4. **Escape Special Characters**: Escape embedded quotes and column specifiers (`:`).
5. **Empty / Garbage Fallback**: Return empty result set immediately for empty or pure punctuation queries.

---

## 6. BM25 Relevance Scoring & Snippet Contract

### 1. Column Weighting in BM25
The search query applies weighted relevance scoring:
- `title` weight: **5.0** (High priority)
- `tags` weight: **3.0** (Categorical relevance)
- `summary` weight: **2.0** (High density)
- `clean_text` weight: **1.0** (Full-body match)

```sql
SELECT 
    f.id,
    bm25(canonical_articles_fts, 5.0, 1.0, 2.0, 3.0) AS rank,
    snippet(canonical_articles_fts, 1, '<mark>', '</mark>', '...', 20) AS title_snippet,
    snippet(canonical_articles_fts, 2, '<mark>', '</mark>', '...', 32) AS text_snippet,
    snippet(canonical_articles_fts, 3, '<mark>', '</mark>', '...', 24) AS summary_snippet
FROM canonical_articles_fts f
WHERE canonical_articles_fts MATCH :query
ORDER BY rank
LIMIT :limit OFFSET :offset;
```

### 2. Search Result Contract
```python
@dataclass(frozen=True, slots=True)
class ArticleSearchResult:
    article: NormalizedArticle
    relevance_score: float  # Normalized BM25 score
    snippet: str            # Contextual match snippet with <mark> tags
```

---

## 7. Repository Protocol & API Delivery Boundary

### 1. `ArticleRepositoryProtocol` Extension:
```python
async def search_articles_fts(
    self,
    query: str,
    limit: int = 50,
    offset: int = 0,
    source_id: Optional[str] = None,
    tag: Optional[str] = None,
) -> List[ArticleSearchResult]:
    """Execute ranked full-text search against canonical FTS5 index."""
    ...
```

### 2. FastAPI Endpoint (`/api/v1/articles/search`):
- **Path**: `GET /api/v1/articles/search`
- **Query Parameters**:
  - `q`: Search query string (required, min length 1, max length 200).
  - `limit`: Integer pagination limit (default 20, max 100).
  - `offset`: Integer pagination offset (default 0).
  - `source_id`: Optional filter by source ID.
  - `tag`: Optional filter by topic/tag.
- **Response**: JSON array of matching articles with `relevance_score` and `snippet`.

---

## 8. Subphase 6C Execution Plan

```text
Subphase 6C: SQLite FTS5 Full-Text Search Integration
├── 6C-A: Architecture Review & Design Approval (Current Gate)
├── 6C-B: Storage DDL, Triggers, FTS Query Sanitizer & Repository Search Method
├── 6C-C: FastAPI Search Endpoint Integration (/api/v1/articles/search)
├── 6C-D: Consistency, Concurrency, Mutation Triggers & Fuzz Verification
└── 6C-E: Full Regression, Report & Milestone Commit
```

---

## 9. Gate 6C-A Recommendation

Gate **6C-A** establishes a zero-debt, ACID-consistent, protocol-isolated full-text search architecture that preserves the frozen Phase 5 storage foundation.

**Gate 6C-A Status**: **SUBMITTED FOR REVIEW & AUTHORIZATION** ✅  
**Ready for**: **Subphase 6C-B Implementation**.
