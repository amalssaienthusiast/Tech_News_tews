# Phase 3 Revisions: Contract Reconciliation & Architectural Refinements

**Document Status**: Phase 3 Architecture Revisions  
**Authority**: Principal Architect  
**Scope**: Reconciliation of Phase 3 design documents with approved Phase 2 domain contracts and strict engineering rules

---

## 1. Domain Contract Reconciliations

### 1.1 FreshnessLevel Contract Alignment
Phase 3 design is strictly reconciled to use the canonical `FreshnessLevel` enum defined in `src/domain/enums.py`:

```python
class FreshnessLevel(str, Enum):
    BREAKING = "breaking"       # [0, 5] minutes
    VERY_FRESH = "very_fresh"   # (5, 30] minutes
    FRESH = "fresh"             # (30, 120] minutes
    RECENT = "recent"           # (120, 360] minutes (2-6 hours)
    AGING = "aging"             # (360, 1440] minutes (6-24 hours)
    OLD = "old"                 # (1440, 4320] minutes (24-72 hours)
    STALE = "stale"             # > 4320 minutes (>72 hours) -> Discard/Archive
    UNKNOWN = "unknown"         # Undated article fallback
```
*Correction*: Removed preliminary references to `REALTIME`, `ARCHIVE`, and `EXPIRED`. Stage 2 evaluates `FreshnessLevel.from_age_minutes()` and drops articles evaluated as `STALE` (age > 72 hours).

---

### 1.2 DedupAction Contract Alignment
Phase 3 design is strictly reconciled to use the canonical `DedupAction` enum defined in `src/domain/enums.py`:

```python
class DedupAction(str, Enum):
    ACCEPTED = "accepted"                          # Genuinely unique -> proceed to indexing
    EXACT_URL_DUPLICATE = "exact_url_duplicate"    # Exact canonical URL match
    SIMILAR_TITLE_DUPLICATE = "similar_title_dup"  # MinHash Jaccard similarity >= threshold
    SUPERSEDED = "superseded"                      # Better revision of existing story
```
*Correction*: Removed preliminary draft names (`ALLOW`, `REJECT`, `CLUSTER`). Stage 5 emits `DedupDecision(action=DedupAction.ACCEPTED, ...)` when an article is unique.

---

### 1.3 EventStatus Contract Alignment
Phase 3 design is strictly reconciled to use the canonical `EventStatus` enum defined in `src/domain/enums.py`:

```python
class EventStatus(str, Enum):
    SUSPECTED = "suspected"         # 1 source, low confidence (<0.30)
    CORROBORATED = "corroborated"   # Multiple sources agree (0.30–0.60)
    CONFIRMED = "confirmed"         # Primary or high-tier source confirmed (0.60–0.85)
    DEVELOPING = "developing"       # Active breaking updates (>0.85 and active updates)
    RESOLVED = "resolved"           # Event complete; no further updates expected
    STALE = "stale"                 # Inactive > 24h
```
*Correction*: Removed all references to nonexistent `ACTIVE` status. New events start in `SUSPECTED` or `CONFIRMED` and transition according to corroboration and age.

---

### 1.4 QualityReport Contract Alignment
Phase 3 design is strictly reconciled to use the canonical `QualityReport` contract defined in `src/domain/models.py`:

- Field name: `is_passed: bool` (NOT `passed`).
- Scores: `quality_score: float` in `[0.0, 1.0]` and `relevance_score: float` in `[0.0, 1.0]`.
- Rejection reasons: `rejection_reasons: Tuple[str, ...]` (non-empty whenever `is_passed == False`).

---

## 2. Stage Ownership & Responsibilities

### Explicit Separation: Relevance vs. Quality
| Stage | Ownership & Responsibilities | Output Metrics |
|:---|:---|:---|
| **Stage 3: Tech Relevance Filter** | Domain relevance verification (Technology, Computer Science, AI, Security, Engineering vs sports, politics, gossip). | `relevance_score: float`, `detected_categories`, `matched_keywords`. |
| **Stage 4: Quality Gate** | Technical and content hygiene (minimum length, formatting cleanliness, boilerplate ratio, clickbait detection, paywall/truncation check). | `quality_score: float`, `rejection_reasons`. Combined with Stage 3 into immutable `QualityReport(is_passed=...)`. |

---

## 3. Formalized Pipeline Numbering: Ingress + 11 Stages

```text
Ingress:   SourceObservationIngress (Zombie Hunt Callback Adapter)
  │
Stage 1:   ObservationNormalizer (SourceObservation -> NormalizedArticle)
Stage 2:   FreshnessEvaluator (FreshnessLevel calculation)
Stage 3:   TechRelevanceFilter (relevance_score & topic detection)
Stage 4:   QualityGate (quality_score & is_passed -> QualityReport)
Stage 5:   DedupEvaluator (DedupDecision generation - read-only)
Stage 6:   DedupCommitter (cache commit ONLY if is_passed & DedupAction.ACCEPTED)
Stage 7:   EventClusterer (NormalizedArticle -> TechEvent)
Stage 8:   ScoringEngine (confidence, importance, novelty & is_breaking)
Stage 9:   ContentEnricher (async summarization & takeaway synthesis)
Stage 10:  PersistenceBridge (atomic persist to EventStore & ArticleStore)
Stage 11:  PublicationDispatch (PublicationBus.publish(PublicationEvent))
```

---

## 4. PublicationBus: High-Priority Breaking Alert Safety

When subscriber queues approach capacity (`maxsize=1000`), the interaction between `PublicationPriority.HIGH` and `DROP_OLDEST` is strictly defined:

1. **Non-Blocking Invariant**: Under no circumstance does `publish()` block the pipeline.
2. **Priority Preservation**: When a subscriber queue is full and a `HIGH` priority event (`BREAKING_ALERT`) is published:
   - The queue scanner drops the oldest `NORMAL` or `LOW` priority event first.
   - Only if all 1,000 pending events are `HIGH` priority does it evict the oldest `HIGH` event.
3. **Audit Logging**: Every dropped event increments `subscriber.dropped_count` and triggers diagnostic warnings at 50-drop intervals.

---

## 5. Rollback Discipline: No Automatic Threshold Weakening

- **Strict Safety Rule**: If false-positive rejections exceed tolerance (> 5%), the system **MUST NOT** dynamically or automatically weaken thresholds at runtime.
- **Rollback Procedure**:
  1. Immediately toggle `ENABLE_CANONICAL_PIPELINE=False` to restore the legacy path.
  2. Inspect the rejection audit trail in `QualityReport` logs.
  3. Formulate revised thresholds in an explicit architectural revision with regression test backing.
  4. Obtain review approval before re-enabling.

---

## 6. Measurable Stage Latency Budgets

Replaced blanket total-pipeline latency with stage-level measurable p95 budgets:

| Stage | Name | Target p95 Budget | Nature |
|:---:|:---|:---:|:---|
| **S1** | ObservationNormalizer | `< 2.0 ms` | Synchronous CPU (URL parse, SHA-256) |
| **S2** | FreshnessEvaluator | `< 0.5 ms` | Synchronous CPU (datetime subtraction) |
| **S3** | TechRelevanceFilter | `< 4.0 ms` | Synchronous CPU (keyword/token scan) |
| **S4** | QualityGate | `< 4.0 ms` | Synchronous CPU (length, boilerplate check) |
| **S5** | DedupEvaluator | `< 5.0 ms` | In-Memory Read (Bloom + MinHash lookup) |
| **S6** | DedupCommitter | `< 2.0 ms` | In-Memory Write (index update) |
| **S7** | EventClusterer | `< 15.0 ms` | In-Memory Cluster Comparison |
| **S8** | ScoringEngine | `< 2.0 ms` | Synchronous CPU (heuristic calculation) |
| **S10**| PersistenceBridge | `< 10.0 ms` | Asynchronous Storage (batch SQLite/WAL) |
| **S11**| PublicationDispatch | `< 0.5 ms` | Non-blocking Queue Push |
| **Core**| **Stages 1–8, 10–11 Total** | **`< 45.0 ms`** | **Total Ingestion Path (p95)** |
| **S9** | ContentEnricher | `< 2500.0 ms` | **Isolated Background Async Task (LLM)** |
