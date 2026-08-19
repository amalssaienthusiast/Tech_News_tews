# Phase 3 Final Architectural Decisions & Approval Gate

**Authority**: Principal Architect  
**Date**: 2026-08-14  
**Verdict**: **APPROVE PHASE 3A** ✅

---

## 1. Architectural Reconciliation Verdict

All preliminary contract mismatches in Phase 3 design have been reconciled and locked against the canonical Phase 2 domain contracts (`src/domain/enums.py` and `src/domain/models.py`).

The architecture for **Phase 3 (Canonical Sequential Pipeline)** is fully reconciled, and **Subphase 3A (Pipeline Protocols & Ingestion Adapters)** is **APPROVED FOR IMPLEMENTATION**.

---

## 2. Reconciled Contract Reference Summary

| Concept | Approved Canonical Contract | Enforced Invariant |
|:---|:---|:---|
| **Freshness** | `FreshnessLevel` (`BREAKING`, `VERY_FRESH`, `FRESH`, `RECENT`, `AGING`, `OLD`, `STALE`, `UNKNOWN`) | `STALE` (>72h) articles are dropped. |
| **Deduplication** | `DedupAction` (`ACCEPTED`, `EXACT_URL_DUPLICATE`, `SIMILAR_TITLE_DUPLICATE`, `SUPERSEDED`) | Evaluate is read-only; Commit occurs ONLY on `ACCEPTED` and `is_passed=True`. |
| **Event State** | `EventStatus` (`SUSPECTED`, `CORROBORATED`, `CONFIRMED`, `DEVELOPING`, `RESOLVED`, `STALE`) | Nonexistent `ACTIVE` status eliminated. |
| **Quality** | `QualityReport` (`is_passed: bool`, `quality_score: float`, `relevance_score: float`) | Explicit rejection codes provided on failure. |
| **Breaking Alert** | `TechEvent.is_breaking` | `freshness == FreshnessLevel.BREAKING and confidence >= 0.70 and importance >= 0.60`. |
| **Pipeline Stages** | Ingress + 11 distinct sequential stages | Deterministic linear processing flow. |
| **Backpressure** | `PublicationBus` Priority-Aware `DROP_OLDEST` | `HIGH` priority breaking alerts are preserved during queue congestion. |
| **Safety** | No automatic threshold weakening | Regressions trigger instant feature flag fallback to legacy path. |
| **Latency Budget** | Stage-level measurable budgets | Core ingestion path `< 45ms` (p95); async enrichment isolated `< 2500ms`. |

---

## 3. Subphase 3A Authorization & Scope

Gemini 3.6 Flash is authorized to implement **Subphase 3A only**:

### Allowed Files for Phase 3A:
1. `src/pipeline/__init__.py` [NEW]
2. `src/pipeline/protocols.py` [NEW] — `PipelineStage` protocol and `PipelineContext`.
3. `src/pipeline/adapters.py` [NEW] — `SourceObservationAdapter` converting legacy emissions to `SourceObservation`.
4. `tests/test_pipeline_protocols.py` [NEW] — Unit tests for pipeline stage protocols, context propagation, and observation adaptation.

### STRICTLY FORBIDDEN During Phase 3A:
- ❌ DO NOT modify `src/zombies/` crawlers
- ❌ DO NOT modify `src/engine/unified_chain.py`
- ❌ DO NOT modify `src/engine/dedup_gate.py` or `src/engine/quality_gate.py`
- ❌ DO NOT modify `src/events/`
- ❌ DO NOT modify `gui_qt/`
- ❌ DO NOT modify database implementations
- ❌ DO NOT upgrade third-party dependencies
- ❌ DO NOT implement stages 3B through 3H yet

---

## 4. Subphase 3A Verification Criteria

1. `tests/test_pipeline_protocols.py` passes 100%.
2. Full cumulative test suite (95+ tests) passes with exit code 0.
3. Zero changes to existing runtime execution behavior.
4. Clean git commit on `rebuild/phase-3-canonical-pipeline`.
