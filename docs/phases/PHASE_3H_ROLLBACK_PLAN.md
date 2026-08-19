# Phase 3H Rollback Plan: Post-Decommission Safety & Recovery

**Document Version**: 1.0.0  
**Status**: APPROVED ROLLBACK SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Safety Anchor & Checkpoint

Phase 3 is permanently anchored at git tag:
```text
phase-3-complete-2026-08-14 (Commit: 07d72c1)
```

Before any file deletion is committed in 3H:
- The entire 174-test suite is verified on `main`.
- All deletions occur in isolated, incremental subphase commits (3H-A -> 3H-B -> 3H-C -> 3H-D -> 3H-E).

---

## 2. Recovery Scenarios & Procedures

### Scenario A: Rollback during Subphase 3H-A or 3H-B (Pre-Deletion)
If an anomaly is detected while switching default mode or removing callers:
- Revert environment flag:
  ```bash
  export CANONICAL_PIPELINE_MODE="legacy"
  ```
- Or revert local commit:
  ```bash
  git revert --no-edit HEAD
  ```

### Scenario B: Rollback after File Deletion in Subphase 3H-C
If unexpected runtime regressions occur after deleting legacy modules:
- Restore directly to the clean Phase 3 complete anchor:
  ```bash
  git checkout phase-3-complete-2026-08-14 -- src/engine/ src/events/
  python3 -m pytest tests/test_*.py -q
  ```
- Or reset to the tag:
  ```bash
  git reset --hard phase-3-complete-2026-08-14
  ```

---

## 3. Post-3H Canonical Rollback Policy

Once Phase 3H is complete and verified:
- Rollback of individual pipeline stages (e.g. S08 scoring algorithm or S05 dedup thresholds) occurs through configuration parameters or stage versioning within `src/pipeline/stages/`.
- The system no longer maintains dual execution paths, eliminating cognitive complexity and duplicate failure modes.
