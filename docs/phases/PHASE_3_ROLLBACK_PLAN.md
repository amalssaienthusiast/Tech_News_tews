# Phase 3 Rollback Plan & Safety Gates

**Document Status**: Phase 3 Architecture Design  
**Authority**: Principal Architect  
**Scope**: Fault-Tolerance, Feature Flags, and Subphase Rollback Procedures

---

## 1. Safety Architecture: Dual-Run & Feature Flags

To prevent ingestion downtime or regressions during the Phase 3 migration, a runtime feature flag mechanism allows instant switching between the legacy pipeline and the canonical pipeline.

```text
                               ┌───────────────────────────┐
                               │ Zombie Emits Observation  │
                               └─────────────┬─────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       │ Feature Flag: ENABLE_CANONICAL_PIPELINE   │
                       └─────────────┬─────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼ (True)                                ▼ (False / Fallback)
    ┌─────────────────────────┐             ┌─────────────────────────┐
    │   Canonical Sequential  │             │   Legacy Feed Chain     │
    │         Pipeline        │             │   & Event Brain Fork    │
    └─────────────────────────┘             └─────────────────────────┘
```

---

## 2. Subphase Rollback Points

| Subphase | Trigger Condition | Rollback Action |
|:---|:---|:---|
| **Phase 3A** | Ingestion adapter errors or type mismatches | Revert to direct `EventSource` consumption; discard adapter wrapper. |
| **Phase 3B** | URL normalizer corrupts valid query parameters | Restore legacy URL cleanup in `unified_chain.py`. |
| **Phase 3C** | Filter drops false positives (> 10% valid tech news) | Lower rejection thresholds (`relevance < 0.25`, `quality < 0.30`) or bypass filter. |
| **Phase 3D** | Dedup evaluator leaks duplicates or blocks unique stories | Fall back to legacy `DedupGate.check_and_add()`. |
| **Phase 3E** | Clustering incorrectly merges disparate events | Restore legacy `EventClusterer` in-memory clustering. |
| **Phase 3F** | Breaking alerts fail to trigger or spam false alarms | Adjust scoring weights; revert to manual threshold check. |
| **Phase 3G** | Pipeline runner performance bottleneck (> 200ms per item) | Switch `ENABLE_CANONICAL_PIPELINE=False` while profiling. |
| **Phase 3H** | Post-retirement regression discovered | Revert git commit removing legacy code; git tag `phase-2-complete-2026-08-14` is the baseline anchor. |

---

## 3. Git Checkpoint Anchors

- Base Anchor: Tag `phase-2-complete-2026-08-14` (commit `35e4519`).
- Subphase Branching: All Phase 3 subphases will be developed on `rebuild/phase-3-canonical-pipeline`.
- Atomic Commits: Each subphase must be committed with its own focused commit after automated test verification.
