# Phase 3 Component Inventory: Ingestion & Pipeline Audit

**Document Status**: Phase 3 Architecture Design  
**Authority**: Principal Architect  
**Scope**: Complete inventory of existing ingestion, filtering, dedup, clustering, and publication stages

---

## 1. Executive Summary

This inventory audits every stage, entry point, model, and gate currently operating in the ingestion lifecycle, mapping current legacy components to their canonical target replacements in Phase 3.

---

## 2. Ingestion Entry Points & Current Path Analysis

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CURRENT FRAGMENTED FLOW                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Ingestion: Zombies emit EventSource / SourceDescriptor              │
│ 2. Fork in unified_chain.py:                                           │
│    ├─ Fork A (Event Brain):                                            │
│    │    EventClusterer.process_article()                               │
│    │    → ConfidenceEngine.score()                                     │
│    │    → FreshnessGate.score()                                        │
│    │    → PublicationBus.publish()                                     │
│    │                                                                   │
│    └─ Fork B (Legacy Feed Chain):                                      │
│         Convert to core.types.Article                                  │
│         → DedupGate.check_and_add() [POISONS DEDUP BEFORE QUALITY]     │
│         → QualityGate.check()                                          │
│         → ContentEnhancer._enhance_and_push()                          │
│         → FeedChain.push()                                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Comprehensive Stage Audit & Disposition

| Pipeline Stage | Current Implementation | Location | Issues & Deficiencies | Target Disposition in Phase 3 |
|:---|:---|:---|:---|:---|
| **Entry Point** | Zombie swarm callbacks | `src/zombies/` | Emits heterogeneous data structures (`EventSource`, dicts). | **Retain Zombies**, wrap emitted items with `SourceObservationAdapter`. |
| **Observation Parsing** | Ad-hoc dict / dataclass parsing | `src/engine/unified_chain.py` | Inconsistent timestamp parsing, lack of timezone validation. | Replace with canonical `SourceObservation` contract. |
| **Normalization** | Fragmented string cleanup | `src/engine/unified_chain.py`, `src/events/` | Redundant URL normalizers, inconsistent canonical URL hashing. | Implement canonical `Stage 1: Normalizer` producing `NormalizedArticle`. |
| **Freshness Evaluation** | `FreshnessGate` | `src/events/freshness_gate.py` | Uses arbitrary float decay instead of discrete `FreshnessLevel` buckets. | Implement `Stage 2: FreshnessGate` enforcing strict `FreshnessLevel` boundaries. |
| **Tech Relevance** | Ad-hoc keyword filters | `src/engine/quality_gate.py` | Mixed with general quality checks; no explainable rejection codes. | Implement `Stage 3: TechRelevanceFilter` returning `QualityReport`. |
| **Quality Evaluation** | `QualityGate` | `src/engine/quality_gate.py` | Boolean return only; cannot explain why an article was rejected. | Implement `Stage 4: QualityGate` producing `QualityReport` with reason codes. |
| **Deduplication** | `DedupGate` | `src/engine/dedup_gate.py` | `check_and_add()` marks seen immediately; poisons cache if quality fails. | Split into `Stage 5: DedupEvaluator.evaluate()` and `Stage 6: DedupCommitter.commit()`. |
| **Event Clustering** | `EventClusterer` | `src/events/event_clusterer.py` | Tightly coupled with legacy models and in-memory dicts. | Adapt `Stage 7: EventClusterer` to accept `NormalizedArticle` and emit `TechEvent`. |
| **Scoring / Breaking** | `ConfidenceEngine` | `src/events/confidence_engine.py` | Breaking derived from single-source arrival; missing multi-tier heuristics. | Implement `Stage 8: ScoringEngine` calculating confidence, importance, novelty. |
| **Enrichment** | `ContentEnhancer` | `src/engine/content_enhancer.py` | Async background tasks with unmanaged error boundaries. | Wrap in `Stage 9: EnrichmentStage` with bounded concurrency. |
| **Persistence** | `EventStore` | `src/events/event_store.py` | SQLite synchronous operations mixed in async loop. | Interface with `Stage 10: PersistenceBridge` preparing for Phase 6. |
| **Publication** | `PublicationBus` | `src/engine/publication_bus.py` | Decoupled in Phase 2C. | Fully connect as `Stage 11: PublicationDispatch`. |

---

## 4. Retained vs. Adapted vs. Retired Matrix

| Component | Status | Action Plan |
|:---|:---:|:---|
| `PublicationBus` | **Retained (Golden)** | Core delivery backbone established in Phase 2C. |
| `src/domain/` models | **Retained (Golden)** | Authoritative contracts established in Phase 2B. |
| `EventClusterer` | **Adapted** | Wrapped to ingest `NormalizedArticle` without breaking clustering heuristics. |
| `ConfidenceEngine` | **Adapted** | Standardized to update `TechEvent` domain invariants. |
| `DedupGate` | **Refactored** | Decomposed into evaluate-before-commit architecture. |
| `QualityGate` | **Refactored** | Converted to output structured `QualityReport`. |
| `FeedChain` | **Retired (Gradual)** | Replaced by `PublicationBus` and canonical storage. |
| `_enhance_and_push` | **Retired (Gradual)** | Replaced by sequential enrichment stage. |
