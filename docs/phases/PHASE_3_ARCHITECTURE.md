# Phase 3 Architecture: Canonical Sequential Pipeline

**Document Status**: Phase 3 Architecture Design  
**Authority**: Principal Architect  
**Scope**: End-to-End Architectural Specification for the Canonical Pipeline

---

## 1. Architectural Philosophy & Target Topology

Phase 3 unifies the historically split ingestion and processing pipelines into a single, deterministic, linear, and observable processing chain governed by canonical domain contracts.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   CANONICAL SEQUENTIAL PIPELINE                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  [Zombie Swarm / Ingestion Adapter]                                    │
│         │ (emits)                                                      │
│         ▼                                                              │
│  SourceObservation                                                     │
│         │                                                              │
│         ▼                                                              │
│  [Stage 1: Normalizer] ──────────────────► NormalizedArticle           │
│         │                                                              │
│         ▼                                                              │
│  [Stage 2: Freshness Gate] ──────────────► Drop if EXPIRED             │
│         │                                                              │
│         ▼                                                              │
│  [Stage 3: Tech Relevance Filter] ───────► Drop if Non-Tech            │
│         │                                                              │
│         ▼                                                              │
│  [Stage 4: Quality Gate] ────────────────► Drop if Low Quality         │
│         │                                  (Emits QualityReport)       │
│         ▼                                                              │
│  [Stage 5: Dedup Evaluator] ─────────────► Evaluate without committing │
│         │                                  (Emits DedupDecision)       │
│         ▼                                                              │
│  [Stage 6: Dedup Committer] ─────────────► Commit to seen index        │
│         │                                  (ONLY if Approved)          │
│         ▼                                                              │
│  [Stage 7: Event Clusterer] ─────────────► TechEvent (Spawn or Merge)  │
│         │                                                              │
│         ▼                                                              │
│  [Stage 8: Scoring & Breaking Engine] ───► Confidence / Importance     │
│         │                                                              │
│         ▼                                                              │
│  [Stage 9: Enrichment Stage] ────────────► Summarization & Takeaways   │
│         │                                                              │
│         ▼                                                              │
│  [Stage 10: Persistence Stage] ──────────► EventStore & ArticleStore   │
│         │                                                              │
│         ▼                                                              │
│  [Stage 11: Publication Dispatch] ───────► PublicationBus.publish()    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Granular Stage Contract & Invariant Specifications

### Stage 1: Observation Normalizer
- **Input**: `SourceObservation`
- **Output**: `NormalizedArticle`
- **Invariants**:
  - URL canonicalized (lowercase domain, strip UTM parameters, strip fragments).
  - Canonical URL hash computed via SHA-256 (`article_id`).
  - Title cleaned (strip HTML entities, leading/trailing whitespace).
  - Author and published timestamp parsed to timezone-aware UTC (`datetime(..., tzinfo=UTC)`).

### Stage 2: Freshness Gate
- **Input**: `NormalizedArticle`
- **Output**: Pass to Stage 3 or Drop (`REJECTED_STALE`)
- **Invariants**:
  - Computes `age_seconds = (now_utc - article.published_at).total_seconds()`.
  - Determines `FreshnessLevel`:
    - `REALTIME`: `< 300s` (5 min)
    - `FRESH`: `300s - 3600s` (1 hour)
    - `RECENT`: `3600s - 86400s` (24 hours)
    - `ARCHIVE`: `86400s - 604800s` (7 days)
    - `EXPIRED`: `> 604800s` (7+ days)
  - Articles with `EXPIRED` status are dropped with audit log.

### Stage 3: Technology Relevance Filter
- **Input**: `NormalizedArticle`
- **Output**: Pass to Stage 4 or Drop (`REJECTED_OFF_TOPIC`)
- **Invariants**:
  - Evaluates domain keyword density, entity matches, and non-tech exclusion terms.
  - Scores `relevance_score` in range `[0.0, 1.0]`.
  - Rejection threshold: `relevance_score < 0.40`.

### Stage 4: Quality Gate
- **Input**: `NormalizedArticle`
- **Output**: `(NormalizedArticle, QualityReport)`
- **Invariants**:
  - Evaluates clickbait indicators, minimum word count, boilerplate ratio, formatting cleanliness.
  - Generates immutable `QualityReport` with explainable rejection codes (`LOW_QUALITY`, `CLICKBAIT`, `SPAM`, `TRUNCATED`).
  - Rejection threshold: `quality_score < 0.50`.

### Stage 5: Dedup Evaluator (`evaluate()`)
- **Input**: `NormalizedArticle`
- **Output**: `DedupDecision`
- **Invariants**:
  - Checks exact URL hash match, canonical URL match, and MinHash/SimHash title similarity.
  - **CRITICAL**: DOES NOT mutate or write to the seen index during evaluation.
  - Emits `DedupDecision(action=DedupAction.ALLOW | REJECT | CLUSTER, confidence=...)`.

### Stage 6: Dedup Committer (`commit()`)
- **Input**: `(NormalizedArticle, DedupDecision, QualityReport)`
- **Output**: Pass to Stage 7
- **Invariants**:
  - Commits `canonical_url_hash` and title signatures to the persistence/memory index **ONLY** if:
    1. `QualityReport.passed == True`
    2. `DedupDecision.action == DedupAction.ALLOW`
  - Prevents dedup poisoning where discarded low-quality articles block subsequent valid articles.

### Stage 7: Event Clusterer
- **Input**: `NormalizedArticle`
- **Output**: `TechEvent`
- **Invariants**:
  - Finds existing active `TechEvent` with matching entity/topic vectors within temporal window (48h).
  - If match found: appends `EventSourceEvidence` to `TechEvent.sources` and updates `last_updated`.
  - If no match: instantiates new `TechEvent(id=..., headline=..., status=EventStatus.ACTIVE)`.

### Stage 8: Scoring & Breaking Engine
- **Input**: `TechEvent`
- **Output**: `TechEvent` (updated with scores)
- **Invariants**:
  - Calculates `confidence` based on source tiers and multi-source corroboration:
    - Tier 1 source: base confidence `0.70`
    - Tier 2 source: base confidence `0.50`
    - Multi-source agreement (+0.15 per distinct tier/species)
  - Evaluates `is_breaking`:
    - `is_breaking = True` IF (`confidence >= 0.70` AND `freshness == REALTIME` AND `importance >= 0.60`).
    - Breaking alerts NEVER depend on arrival velocity alone.

### Stage 9: Content Enrichment
- **Input**: `TechEvent`
- **Output**: `TechEvent` (enriched)
- **Invariants**:
  - Generates structured 3-bullet summary, key takeaways, and named entity tags.
  - Bounded async execution with fallback to raw article summary on timeout.

### Stage 10: Persistence Stage
- **Input**: `TechEvent`
- **Output**: `TechEvent`
- **Invariants**:
  - Persists event and source links atomically to `EventStore`.

### Stage 11: Publication Dispatch
- **Input**: `TechEvent`
- **Output**: Dispatches to `PublicationBus`
- **Invariants**:
  - Constructs `PublicationEvent` with `PublicationChannel.SSE_STREAM`, `TELEGRAM_BOT`.
  - Sets `priority = PublicationPriority.HIGH` if `is_breaking`, else `NORMAL`.
  - Calls `await bus.publish(pub_event)`.

---

## 3. High-Priority Breaking Alert Safety

To ensure `DROP_OLDEST` in `PublicationBus` never silently drops a high-priority breaking alert during heavy subscriber queue backpressure:
1. `PublicationEvent.priority == HIGH` bypasses standard FIFO drop.
2. If subscriber queue is full and incoming event is `HIGH` priority, the queue scanner drops the oldest `NORMAL` or `LOW` event instead of dropping indiscriminately.
