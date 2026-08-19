# Phase 3G Test Plan: End-to-End Canonical Ingestion Verification

**Document Version**: 1.0.0  
**Status**: APPROVED DESIGN SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Scope & Strategy

The Phase 3G test suite (`tests/test_canonical_pipeline_runner.py`) provides exhaustive verification of the integrated sequential pipeline:
1. Full end-to-end ingestion happy path (`SourceObservation` -> `PublicationBus`).
2. Exact stage drop behavior for all filter stages (S02 Stale, S03 Non-tech, S04 Low quality, S05 Duplicate).
3. Dedup poisoning prevention under full pipeline execution.
4. Multi-source event corroboration and timeline evolution through the pipeline.
5. Derived breaking news event publication with `PublicationPriority.HIGH`.
6. Feature flag routing (`active`, `shadow`, `legacy`).
7. Zero dual-publication invariant in all modes.
8. Bounded concurrency, backpressure, and thread-safety under parallel ingestion.
9. Error isolation (malformed item does not crash or block runner).

---

## 2. Test Cases Matrix

| Test ID | Test Name | Ingestion Input | Expected Outcome |
|:---|:---|:---|:---|
| **TC-3G-01** | `test_full_pipeline_happy_path` | High-quality tech observation | Processes S01–S11 cleanly; publishes `PublicationEvent` to bus; records metrics for all stages. |
| **TC-3G-02** | `test_pipeline_drops_stale_at_s02` | Observation published 80 hours ago | Dropped at S02; abort reason recorded; S03–S11 skipped; zero bus publication. |
| **TC-3G-03** | `test_pipeline_drops_non_tech_at_s03` | Real estate / celebrity gossip observation | Dropped at S03; S04–S11 skipped; zero dedup commit; zero bus publication. |
| **TC-3G-04** | `test_pipeline_drops_low_quality_at_s04` | Clickbait short spam article | Dropped at S04; S05/S06 skip commit; zero dedup poisoning; zero bus publication. |
| **TC-3G-05** | `test_pipeline_drops_duplicate_at_s05` | Ingest identical URL twice | 1st item succeeds and publishes; 2nd item dropped at S05 as duplicate; zero duplicate publication. |
| **TC-3G-06** | `test_multi_source_event_corroboration` | 2 related articles from distinct Tier 1/2 publishers | 1st creates event; 2nd merges into same event, updates timeline, increases confidence, and publishes update. |
| **TC-3G-07** | `test_breaking_news_event_publication` | Breaking Tier 1 zero-day CVE story | Scored with `is_breaking=True`; published with `PublicationPriority.HIGH`. |
| **TC-3G-08** | `test_shadow_mode_no_duplicate_publication` | Ingestion under `CANONICAL_PIPELINE_MODE="shadow"` | Canonical runner runs with `dry_run=True`; bus receives exactly 1 event from legacy pipeline; zero duplicate publication. |
| **TC-3G-09** | `test_concurrency_and_backpressure` | 50 concurrent observations across 8 workers | All items processed safely; zero race conditions; dedup index and event store maintain integrity. |
| **TC-3G-10** | `test_error_isolation_unhandled_exception` | Ingest item that triggers mock stage exception | Exception caught and logged; runner returns error result; subsequent valid items process successfully. |

---

## 3. Execution Verification

1. Targeted suite: `python3 -m pytest tests/test_canonical_pipeline_runner.py -v` (10/10 passing).
2. Cumulative suite: `python3 -m pytest tests/test_*.py -q` (173+/173+ passing).
