# Phase 3G Architecture: Canonical Pipeline Integration

**Document Version**: 1.0.0  
**Status**: APPROVED DESIGN SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  
**Target Subphase**: Subphase 3G (Pipeline Assembly & Runtime Integration)

---

## 1. High-Level System Architecture

Phase 3G bridges the completed canonical pipeline stages (S01–S08) with runtime ingestion, enrichment (S09), persistence (S10), and the application publication bus (S11).

```
                      ┌──────────────────────────────────────────────┐
                      │              Zombie Swarm Ingress            │
                      │ (RSS / Scrapers / APIs / Community Crawlers) │
                      └──────────────────────┬───────────────────────┘
                                             │ (EventSource / Raw Ingest)
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │       SourceObservationAdapter (S00)         │
                      │  (Deterministic Conversion to Domain Model)  │
                      └──────────────────────┬───────────────────────┘
                                             │ SourceObservation
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │          CanonicalPipelineRunner             │
                      │                                              │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S01: ObservationNormalizer             │  │ -> NormalizedArticle
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S02: FreshnessEvaluator                │  │ -> (Rejects STALE >72h)
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S03: TechRelevanceFilter               │  │ -> (Rejects Non-Tech)
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S04: QualityGate (Sets QualityReport)  │  │ -> (Hygiene & Spam Check)
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S05: DedupEvaluator (Read-Only)        │  │ -> (Sets DedupDecision)
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S06: DedupCommitter (Quality Gated)    │  │ -> (Commits ONLY if Valid)
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S07: EventClusterer (48h Window)       │  │ -> TechEvent
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S08: ScoringEngine (Confidence/Imp/Brk)│  │ -> Scored TechEvent
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S09: EnrichmentStage (Non-Blocking)    │  │ -> Enriched TechEvent
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S10: PersistenceStage (Store/Update)   │  │ -> Persisted TechEvent
                      │  └───────────────────┬────────────────────┘  │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ S11: PublicationStage (PublicationBus) │  │ -> PublicationEvent
                      │  └────────────────────────────────────────┘  │
                      └──────────────────────────────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │          Application PublicationBus          │
                      │     (SSE Stream, Telegram, UI Consumers)     │
                      └──────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 `CanonicalPipelineRunner`
- **Location**: `src/pipeline/runner.py`
- **Responsibilities**:
  - Orchestrates sequential stage execution.
  - Instantiates execution-scoped `PipelineContext` for each item.
  - Manages stage lifecycle and error isolation.
  - Handles early termination (rejections/drops) cleanly without exceptions.
  - Emits telemetry and latency metrics per stage.

### 2.2 Stage Responsibilities & Signatures

| Stage | Class | In | Out | Invariant / Responsibility |
|:---|:---|:---:|:---:|:---|
| **S01** | `ObservationNormalizer` | `SourceObservation` | `NormalizedArticle` | URL canonicalization, HTML entity cleanup, UTC normalization. |
| **S02** | `FreshnessEvaluator` | `NormalizedArticle` | `NormalizedArticle` | Drops STALE (>72h); attaches `FreshnessResult`. |
| **S03** | `TechRelevanceFilter` | `NormalizedArticle` | `NormalizedArticle` | Drops non-technology articles; attaches `RelevanceResult`. |
| **S04** | `QualityGate` | `NormalizedArticle` | `NormalizedArticle` | Evaluates content hygiene; attaches `QualityReport` to context. |
| **S05** | `DedupEvaluator` | `NormalizedArticle` | `NormalizedArticle` | Read-only check against `DedupIndex`; attaches `DedupDecision`. Drops duplicates. |
| **S06** | `DedupCommitter` | `NormalizedArticle` | `NormalizedArticle` | Commits to `DedupIndex` **only if** `quality_report.is_passed and action == ACCEPTED`. |
| **S07** | `EventClusterer` | `NormalizedArticle` | `TechEvent` | Correlates article into `TechEvent` within 48h active window. |
| **S08** | `ScoringEngine` | `TechEvent` | `TechEvent` | Evaluates confidence, importance, novelty, freshness, and derives `is_breaking`. |
| **S09** | `EnrichmentStage` | `TechEvent` | `TechEvent` | Non-blocking summarization/metadata enhancement with 2.0s strict timeout. |
| **S10** | `PersistenceStage` | `TechEvent` | `TechEvent` | Persists event aggregate updates into event repository. |
| **S11** | `PublicationStage` | `TechEvent` | `TechEvent` | Publishes `PublicationEvent` to application-scoped `PublicationBus`. |

---

## 3. Concurrency & State Management

1. **State Store Ownership**:
   - `DedupIndex` (S05/S06) and `ActiveEventStore` (S07) are owned by `CanonicalPipelineRunner` and shared across pipeline worker tasks.
   - All state mutations are synchronized internally using `threading.RLock()`.
2. **Task Concurrency**:
   - Ingestion callbacks execute asynchronously via `asyncio.create_task()`.
   - Concurrency is bounded by an `asyncio.Semaphore(max_concurrency)` (default: 16 concurrent pipeline executions).
3. **Publication Decoupling**:
   - Stage 11 publishes to the `PublicationBus` ring-buffer queue, which decouples pipeline processing from downstream consumer delivery (SSE, Telegram).
