# Phase 3 Architectural Decisions & Gate Approval

**Authority**: Principal Architect  
**Date**: 2026-08-14  
**Verdict**: **APPROVE PHASE 3 DESIGN** ✅

---

## 1. Architectural Verdict

The architectural design for **Phase 3: Canonical Sequential Pipeline Migration** is **APPROVED**.

Phase 3 transforms the fragmented, dual-fork pipeline into a single, observable, contract-driven sequential pipeline executed across 8 disciplined subphases (3A through 3H).

---

## 2. Key Architectural Decisions

| Area | Approved Architecture Decision |
|:---|:---|
| **1. Pipeline Topology** | Strict linear sequential pipeline: `SourceObservation -> Normalizer -> Freshness -> TechRelevance -> Quality -> Dedup.evaluate -> Dedup.commit -> Clustering -> Scoring -> Enrichment -> Persistence -> PublicationBus`. |
| **2. Dedup Isolation** | Strictly split into `DedupEvaluator` (read-only decision generation) and `DedupCommitter` (cache commit ONLY after quality approval). Dedup poisoning is completely eliminated. |
| **3. Freshness Evaluation** | Replaced arbitrary float decay with canonical `FreshnessLevel` buckets (`REALTIME`, `FRESH`, `RECENT`, `ARCHIVE`, `EXPIRED`). |
| **4. Explainable Quality** | Replaced boolean `QualityGate` with structured `QualityReport` emitting explicit machine-readable rejection codes. |
| **5. Breaking Alert Rigor** | Breaking status is strictly derived from multi-attribute event state (`confidence >= 0.70 + freshness == REALTIME + importance >= 0.60`), NEVER from raw source arrival. |
| **6. High-Priority Delivery** | High-priority events are prioritized in `PublicationBus` backpressure handling to ensure breaking alerts are never dropped. |
| **7. Dual-Run Safety** | Retain legacy pipeline behind `ENABLE_CANONICAL_PIPELINE` feature flag during migration to ensure zero ingestion downtime. |
| **8. Implementation Cadence** | Executed in 8 incremental subphases (3A to 3H). Gemini implements one subphase at a time, followed by test runs and Claude Opus gate review. |

---

## 3. Strict Boundary Rules for Phase 3 Implementation

Gemini 3.6 Flash must adhere to the following strict boundaries:
- ❌ **DO NOT** rewrite all Zombie crawlers in Phase 3 (wrap with `SourceObservationAdapter` in 3A).
- ❌ **DO NOT** modify the Desktop GUI (`gui_qt/`).
- ❌ **DO NOT** introduce external message brokers (Redis, Kafka, Celery).
- ❌ **DO NOT** redesign database storage engines (Phase 6).
- ❌ **DO NOT** upgrade third-party dependencies.
- ❌ **DO NOT** jump multiple subphases in a single step (implement 3A, test, review, then 3B).

---

## 4. Next Step: Authorize Subphase 3A

Subphase 3A is authorized for implementation:
- Create `src/pipeline/protocols.py`
- Create `src/pipeline/adapters.py`
- Create `tests/test_pipeline_protocols.py`
- Verify zero runtime regressions.
