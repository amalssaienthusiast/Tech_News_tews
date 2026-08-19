# Phase 3 Migration Plan: Canonical Sequential Pipeline

**Document Status**: Phase 3 Architecture Design  
**Authority**: Principal Architect  
**Scope**: Granular Step-by-Step Subphase Execution Plan (Phase 3A through 3H)

---

## 1. Migration Strategy & LLM Division of Labor

The pipeline migration will be executed as a strict sequence of independent subphases. Gemini 3.6 Flash implements one subphase at a time; each subphase is verified with automated tests and reviewed by Claude Opus 4.6 before the next subphase begins.

```text
Phase 3A: Ingestion Adapters & Pipeline Protocols
   ↓ (test + gate approval)
Phase 3B: Normalization Stage (NormalizedArticle)
   ↓ (test + gate approval)
Phase 3C: Filtering & Quality Gates (QualityReport)
   ↓ (test + gate approval)
Phase 3D: Dedup Refactoring (evaluate vs. commit separation)
   ↓ (test + gate approval)
Phase 3E: Event Clustering Adaptation (TechEvent)
   ↓ (test + gate approval)
Phase 3F: Scoring & Breaking Engine (multi-source corroboration)
   ↓ (test + gate approval)
Phase 3G: Canonical Pipeline Assembly & Persistence Integration
   ↓ (test + gate approval)
Phase 3H: Legacy Pipeline Retirement & Dual-Run Validation
```

---

## 2. Granular Subphase Breakdown

### Subphase 3A: Pipeline Protocols & Ingestion Adapters
- **Objective**: Establish the abstract `PipelineStage` interface and `SourceObservationAdapter` without altering existing zombie hunt loops.
- **Files**:
  - `src/pipeline/protocols.py` [NEW] — `PipelineStage` protocol, `PipelineContext`.
  - `src/pipeline/adapters.py` [NEW] — Converts legacy `EventSource` / `SourceDescriptor` to `SourceObservation`.
  - `tests/test_pipeline_protocols.py` [NEW]
- **Verification**: Zero changes to active runtime execution.

### Subphase 3B: Normalization Stage
- **Objective**: Implement `ObservationNormalizer` converting raw `SourceObservation` into strictly validated `NormalizedArticle`.
- **Files**:
  - `src/pipeline/stages/s01_normalizer.py` [NEW]
  - `tests/test_stage_normalizer.py` [NEW]
- **Verification**: URL canonicalization, title cleaning, timezone-aware datetime validation.

### Subphase 3C: Freshness, Relevance & Quality Filtering
- **Objective**: Implement discrete filter stages producing structured `QualityReport` with explicit rejection codes.
- **Files**:
  - `src/pipeline/stages/s02_freshness.py` [NEW]
  - `src/pipeline/stages/s03_relevance.py` [NEW]
  - `src/pipeline/stages/s04_quality.py` [NEW]
  - `tests/test_stage_filters.py` [NEW]
- **Verification**: Explanatory rejection codes, strict `FreshnessLevel` buckets.

### Subphase 3D: Deduplication Refactoring (Evaluate vs. Commit)
- **Objective**: Eliminate dedup poisoning by separating evaluation from cache commitment.
- **Files**:
  - `src/pipeline/stages/s05_dedup_evaluator.py` [NEW]
  - `src/pipeline/stages/s06_dedup_committer.py` [NEW]
  - `tests/test_stage_dedup.py` [NEW]
- **Verification**: Rejected articles never appear in the seen URL index; duplicate detection works accurately across canonical URLs and title hashes.

### Subphase 3E: Event Clustering Adaptation
- **Objective**: Adapt event clustering to consume `NormalizedArticle` and output `TechEvent` domain instances.
- **Files**:
  - `src/pipeline/stages/s07_clustering.py` [NEW]
  - `tests/test_stage_clustering.py` [NEW]
- **Verification**: Multi-source aggregation, temporal windowing (48h), correct timeline generation.

### Subphase 3F: Scoring & Breaking Engine
- **Objective**: Implement multi-tier corroboration scoring and state-derived breaking alert classification.
- **Files**:
  - `src/pipeline/stages/s08_scoring.py` [NEW]
  - `tests/test_stage_scoring.py` [NEW]
- **Verification**: Breaking alerts triggered ONLY when `confidence >= 0.70 AND freshness == REALTIME AND importance >= 0.60`.

### Subphase 3G: Canonical Pipeline Assembly & Publication
- **Objective**: Assemble Stages 1-11 into `CanonicalPipeline` and wire to `PublicationBus`.
- **Files**:
  - `src/pipeline/runner.py` [NEW]
  - `src/engine/unified_chain.py` [MODIFY — wire hunt callbacks to `CanonicalPipeline`]
  - `tests/test_canonical_pipeline_e2e.py` [NEW]
- **Verification**: End-to-end ingestion from Zombie discovery to `PublicationBus` dispatch.

### Subphase 3H: Legacy Pipeline Retirement & Controlled Comparison
- **Objective**: Deprecate legacy `FeedChain` and redundant gates after side-by-side validation.
- **Files**:
  - `src/engine/unified_chain.py` [MODIFY — remove legacy fork]
  - `tests/test_regression_pipeline.py` [NEW]
- **Verification**: Full repository test suite passes with zero legacy pipeline dependencies.
