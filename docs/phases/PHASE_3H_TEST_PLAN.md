# Phase 3H Test Plan: Post-Decommission Validation

**Document Version**: 1.0.0  
**Status**: APPROVED TEST SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Objectives

Verify that:
1. Active production ingestion runs exclusively through `CanonicalPipelineRunner` with zero dependency on deleted legacy modules.
2. Clean shutdown, zombie swarm callback dispatch, and publication bus streaming function without error.
3. Full repository test suite (Phase 1, Phase 2, Phase 3) passes with zero missing import errors or broken test fixtures.

---

## 2. Test Execution Matrix

| Test Suite | Focus Area | Expected Result |
|:---|:---|:---|
| `tests/test_canonical_pipeline_runner.py` | End-to-end canonical pipeline execution, active mode, shadow mode, concurrency | 11/11 PASSED |
| `tests/test_pipeline_protocols.py` | Stage protocols, context tracing, and adapter conversions | 14/14 PASSED |
| `tests/test_stage_normalizer.py` | Stage 1 URL & title normalization | 12/12 PASSED |
| `tests/test_stage_filters.py` | Stage 2 Freshness, Stage 3 Relevance, Stage 4 Quality | 13/13 PASSED |
| `tests/test_stage_dedup.py` | Stage 5 Dedup Evaluator & Stage 6 Dedup Committer | 9/9 PASSED |
| `tests/test_stage_clustering.py` | Stage 7 Event Clusterer & Active Event Store | 9/9 PASSED |
| `tests/test_stage_scoring.py` | Stage 8 Scoring Engine | 11/11 PASSED |
| `tests/test_publication_bus.py` | Layer 4/5 decoupling, async publication, bounded queues | 7/7 PASSED |
| `tests/test_architecture_boundaries.py` | Layer isolation, zero forbidden cross-layer imports | 5/5 PASSED |
| `tests/test_domain_contracts.py` | Pure domain model invariants & validation rules | 26/26 PASSED |
| `tests/test_security_policy.py` | Phase 1A security policies | 29/29 PASSED |
| `tests/test_tls_verification.py` | Strict TLS certificates & pinning | 6/6 PASSED |
| `tests/test_api_security.py` | API key & SSE auth security | 8/8 PASSED |
| `tests/test_telegram_integration.py` | Telegram bot publication integration | 9/9 PASSED |
| `tests/test_deployment_baseline.py` | Phase 1B deployment scripts & health checks | 5/5 PASSED |

---

## 3. Total Expected Cumulative Test Count: **174+ PASSED**
