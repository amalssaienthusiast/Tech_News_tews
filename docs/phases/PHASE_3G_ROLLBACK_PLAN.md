# Phase 3G Rollback Plan: Zero-Downtime Pipeline Rollback

**Document Version**: 1.0.0  
**Status**: APPROVED DESIGN SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Rollback Strategy & Trigger Conditions

Phase 3G incorporates an instant, zero-downtime rollback mechanism via feature flags and runtime mode controls.

### 1.1 Trigger Conditions:
- Unhandled error rate in canonical pipeline exceeds 0.5% over a 5-minute rolling window.
- Ingestion latency per article exceeds 500ms at p99.
- Any dual-publication anomaly detected.
- Any regression in legacy event consumption or downstream subscriber streams.

---

## 2. Rollback Execution Procedure

### Step 1: Immediate Environment Variable Reversion (Zero-Downtime)
Set:
```bash
export ENABLE_CANONICAL_PIPELINE="false"
export CANONICAL_PIPELINE_MODE="legacy"
```
Or in application settings:
```python
ENABLE_CANONICAL_PIPELINE = False
```

### Step 2: Runtime Verification
1. `UnifiedFeedChainEngine._on_zombie_found_source()` immediately routes 100% of traffic to `_run_legacy_ingestion()`.
2. `PublicationBus` continues delivering legacy events to SSE stream and Telegram bot without interruption.
3. In-flight items in `CanonicalPipelineRunner` drain and terminate cleanly.

### Step 3: Git-Level Safe Rollback (If Code Reversion Required)
If a physical code revert is mandated:
```bash
git revert --no-edit <phase-3g-commit-sha>
python3 -m pytest tests/ -q
```
Because legacy classes (`src/engine/dedup_gate.py`, `src/engine/quality_gate.py`, `src/events/event_clusterer.py`) were never modified or deleted, legacy ingestion remains completely intact throughout.

---

## 3. Post-Rollback Postmortem & Review Gate

1. Review audit logs for `abort_reason` and unhandled exceptions in `PipelineContext`.
2. Inspect `DedupIndex` and `ActiveEventStore` diagnostics.
3. Implement fixes in an isolated branch and re-run the 10-point test suite before re-enabling.
