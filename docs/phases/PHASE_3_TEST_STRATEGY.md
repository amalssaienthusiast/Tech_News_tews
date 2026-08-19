# Phase 3 Test Strategy: Canonical Sequential Pipeline

**Document Status**: Phase 3 Architecture Design  
**Authority**: Principal Architect  
**Scope**: Automated Unit, Integration, Regression, and Shadow Comparison Test Strategy

---

## 1. Test Strategy Matrix

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PHASE 3 TEST STRATEGY                           │
├────────────────────────────────────────────────────────────────────────┤
│ Level 1: Stage Unit Tests                                              │
│   - test_stage_normalizer.py (Stage 1)                                │
│   - test_stage_filters.py (Stages 2, 3, 4)                            │
│   - test_stage_dedup.py (Stages 5, 6: evaluate vs commit)              │
│   - test_stage_clustering.py (Stage 7)                                 │
│   - test_stage_scoring.py (Stage 8)                                    │
│                                                                        │
│ Level 2: End-to-End Pipeline Tests                                     │
│   - test_canonical_pipeline_e2e.py (Full flow: Stage 1 -> Stage 11)    │
│   - test_breaking_alert_flow.py (Breaking event to PublicationBus)     │
│                                                                        │
│ Level 3: Architecture & Invariant Enforcement                          │
│   - AST linter: Zero legacy imports in new pipeline stages             │
│   - Immutability assertions on intermediate stage payloads             │
│                                                                        │
│ Level 4: Shadow Run & Regression Verification                          │
│   - Compare legacy vs canonical output on identical source feeds       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Stage-Specific Test Specifications

| Stage | Test File | Key Test Cases | Pass Criteria |
|:---|:---|:---|:---|
| **Normalizer** | `test_stage_normalizer.py` | `test_canonicalize_dirty_urls`<br>`test_clean_title_html_entities`<br>`test_enforce_timezone_aware_utc` | Deterministic SHA-256 ID; stripped tracking query params; valid UTC timestamps. |
| **Filters** | `test_stage_filters.py` | `test_freshness_bucket_assignment`<br>`test_tech_relevance_exclusion`<br>`test_quality_report_rejection_codes` | Accurate `FreshnessLevel`; low-quality items return explainable reason codes. |
| **Dedup** | `test_stage_dedup.py` | `test_evaluate_does_not_mutate_cache`<br>`test_rejected_article_not_committed`<br>`test_exact_and_fuzzy_duplicates` | Cache unchanged after `evaluate()`; cache committed ONLY on `commit()`; no poisoning. |
| **Clustering** | `test_stage_clustering.py` | `test_single_article_spawns_event`<br>`test_related_article_merges_event`<br>`test_temporal_window_expiration` | Correct clustering by entity overlap; timeline updated with source evidence. |
| **Scoring** | `test_stage_scoring.py` | `test_multi_tier_confidence_boost`<br>`test_breaking_alert_strict_conditions`<br>`test_non_breaking_high_confidence` | Breaking alert requires `confidence >= 0.70 + freshness == REALTIME + importance >= 0.60`. |
| **Runner** | `test_canonical_pipeline_e2e.py`| `test_full_pipeline_happy_path`<br>`test_pipeline_rejection_audit_trail`<br>`test_publication_bus_fanout` | Raw observation processes end-to-end and arrives in subscriber queue within 50ms. |
