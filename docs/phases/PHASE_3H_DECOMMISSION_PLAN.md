# Phase 3H Decommission Plan: Phased Retirement of Legacy Runtime

**Document Version**: 1.0.0  
**Status**: APPROVED DECOMMISSION SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Phased Execution Overview

Decommissioning proceeds in 5 disciplined subphases (3H-A through 3H-E). Each subphase requires intermediate test execution and review gates.

```
┌─────────────────────────────────────────────────────────────┐
│ 3H-A: Switch Production Default to Canonical Pipeline        │
│ (Set CANONICAL_PIPELINE_MODE default to 'active')           │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Verify Active Ingestion & Zero Regressions)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3H-B: Decommission Legacy Ingestion Execution Paths in Engine│
│ (Remove _run_legacy_pipeline & legacy gate attributes)       │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Verify UnifiedFeedChainEngine Cleanup)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3H-C: Delete Obsolete Legacy Pipeline & Event Brain Modules │
│ (Delete feed_chain, dedup_gate, quality_gate, etc.)         │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Verify 174+ Test Suite Passes)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3H-D: Clean Unused Imports & Obsolete Compatibility Shims   │
│ (Remove dangling imports and legacy schedulers)             │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Verify Repository Cleanliness)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3H-E: Final Repository Orphan Audit & Verification Gate     │
│ (Final Static Architecture Check & Tagging)                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Subphase Steps

### Subphase 3H-A: Switch Production Default to Canonical Pipeline
- **Target**: `src/engine/unified_chain.py`
- **Action**: Change default in `get_pipeline_mode()` from `"legacy"` to `"active"`.
- **Validation**: Ensure 100% of crawler traffic flows through `CanonicalPipelineRunner`.

### Subphase 3H-B: Decommission Legacy Execution Paths in Engine
- **Target**: `src/engine/unified_chain.py`
- **Action**:
  - Remove legacy pipeline branch `_run_legacy_pipeline()` from `_on_zombie_found_source()`.
  - Remove unused legacy attributes (`self.dedup`, `self.quality`, `self.feed`, `self.enhancer`, `self._event_clusterer`, `self._confidence_engine`, `self._freshness_gate`).
  - Maintain `subscribe()` and `get_articles()` on `UnifiedFeedChainEngine` if needed or wire to publication bus / runner state.

### Subphase 3H-C: Delete Obsolete Pipeline & Event Brain Modules
- **Target Files for Deletion**:
  1. `src/engine/feed_chain.py`
  2. `src/engine/dedup_gate.py`
  3. `src/engine/quality_gate.py`
  4. `src/engine/content_enhancer.py`
  5. `src/engine/breaking_news_pipeline.py`
  6. `src/engine/cyclic_scheduler.py`
  7. `src/events/event_clusterer.py`
  8. `src/events/confidence_engine.py`
  9. `src/events/freshness_gate.py`
  10. `src/events/timeline_builder.py`
  11. `src/events/entity_extractor.py`
- **Retained for Downstream Phases**:
  - `src/events/event_types.py` (`EventSource` used by `src/zombies/`) -> Phase 4
  - `src/events/event_store.py` (`EventStore` used by `src/api/routes/events.py`) -> Phase 5

### Subphase 3H-D: Clean Unused Imports & Obsolete Compatibility Shims
- Clean unused imports in `src/engine/__init__.py` and `src/events/__init__.py`.

### Subphase 3H-E: Final Orphan Audit & Phase 3 Sign-Off
- Run static architecture verification and full regression suite.
- Produce `PHASE_3H_IMPLEMENTATION_REPORT.md`.
