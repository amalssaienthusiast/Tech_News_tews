# Phase 5E-F Architecture Review: Full Phase 5E Cross-Boundary E2E Integration

**Document Version:** 1.0.0  
**Author:** Antigravity Principal Systems Architect & Storage Reviewer  
**Date:** 2026-08-15  
**Baseline Git Commit:** `e80f870` (Subphases 5E-A through 5E-E committed & clean)  
**Cumulative Test Baseline:** `334/334 PASSED`  
**Status:** **APPROVED FOR IMPLEMENTATION**  

---

## 1. Executive Summary & Objective

Subphase 5E-F is the capstone integration and verification subphase for Phase 5E. Its mission is to rigorously prove that the **three canonical memory systems** operate as a single coherent, durable, and restart-resilient platform across the full application lifecycle:

```text
                         INTERNET
                            │
                            ▼
                       ZombieSwarm
                            │
                            ▼
                    SourceObservation
                            │
                            ▼
                 ┌─────────────────────┐
                 │ 11-Stage Pipeline   │
                 │                     │
                 │ S01 → S06           │
                 │    │                │
                 │    ├── Article ─────┼──────► canonical_articles
                 │    │                │
                 │ S07 → S10           │
                 │    │       │        │
                 │    │       └────────┼──────► canonical_events
                 │    │                │
                 │    └─────────────── │
                 └─────────────────────┘
                            │
                            ▼
                   Source Health State
                            │
                            ▼
                  canonical_source_health
                            │
                            ▼
                  ════ PROCESS RESTART ════
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          Articles       S07 Events    Zombie Health
          restored       hydrated       restored
              │             │             │
              └─────────────┼─────────────┘
                            ▼
                         FastAPI
                     ┌──────┴──────┐
                     ▼             ▼
                  Articles       Events
                  REST/SSE       REST/SSE
```

**Final Verdict:** **APPROVED FOR IMPLEMENTATION**

---

## 2. The Three Canonical Memory Systems

| System | Domain Entity | Storage Table | Lifecycle Owner | Startup Hydration | Delivery API |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Article Memory** | `NormalizedArticle` | `canonical_articles` | `CanonicalPipelineRunner` (post-S06) | On-demand pagination / ID lookup | `GET /v1/articles`<br>`GET /v1/articles/{id}` |
| **Event Brain** | `TechEvent` + `EventSourceEvidence` | `canonical_events`<br>`canonical_event_sources` | `CanonicalPipelineRunner` (S07-S10) | `S07_EventClusterer.hydrate()` | `GET /v1/events`<br>`GET /v1/events/{id}`<br>`GET /v1/events/stream` |
| **Health Memory** | `SourceHealth` | `canonical_source_health` | `ZombieSwarm` (supervisory) | `ZombieSwarm.hydrate_health()` | In-memory descriptors / rate limiters |

---

## 3. End-to-End Multi-Lifecycle Verification Experiment

The core test suite in `tests/test_phase5e_f_integration.py` will execute a deterministic 4-stage lifecycle experiment against a single shared SQLite database:

### Stage 1: Initial Discovery & Persistence (Process Context A)
1. **Acquisition & Ingestion:**
   - Source 1 (`techcrunch`) observes Breaking Story X.
   - Swarm records:
     - Source 1 as `HEALTHY` (Tier 1).
     - Source 2 (`theverge`) as `RATE_LIMITED` (30-minute cooldown).
     - Source 3 (`wired`) as `DEGRADED` (1 failure).
2. **Pipeline Execution:**
   - S01 $\to$ S06: Article 1 (`art_5ef_tc`) is validated and saved to `canonical_articles`.
   - S07 $\to$ S10: TechEvent 1 (`evt_5ef_story_x`) is formed with Primary Source 1 and persisted to `canonical_events` + `canonical_event_sources`.
3. **Shutdown & Flush:**
   - Swarm flushes health batch to `canonical_source_health`.
   - Engine and connections are cleanly closed (`await engine.aclose()`).

### Stage 2: Cold Process Restart & Multi-Source Corroboration (Process Context B)
1. **Cold Start & Hydration:**
   - Fresh `SqliteEngine` opening the same `.db` file.
   - `ZombieSwarm.hydrate_health()` restores Source 2's cooldown and Source 3's failure count into in-memory descriptors.
   - S07 Event Clusterer is initialized and hydated from SQLite: TechEvent 1 is loaded into the in-memory clustering index.
2. **Corroborating Ingestion:**
   - Source 2 (`theverge`) observes the same Breaking Story X (different canonical URL, highly similar semantic headline).
   - Pipeline Execution:
     - S01 $\to$ S06: Article 2 (`art_5ef_verge`) is validated and saved to `canonical_articles` (distinct canonical article row).
     - S07 $\to$ S10: S07 matches cluster of TechEvent 1 $\to$ corroborates into the existing TechEvent!
     - TechEvent 1 updated: `sources = [Source 1, Source 2]`, `source_count = 2`, `status = CORROBORATED`.
     - S10 saves updated TechEvent 1.
3. **Outcome & Shutdown:**
   - Swarm records Source 2 success, transitioning it from `RATE_LIMITED` back to `HEALTHY`.
   - Complete shutdown: `await swarm.aclose()`, `await engine.aclose()`.

### Stage 3: Direct SQLite Table Integrity Verification
Direct SQL query verification against the `.db` file confirming:
- `canonical_articles`: Exactly 2 rows (`art_5ef_tc`, `art_5ef_verge`).
- `canonical_events`: Exactly 1 row (`evt_5ef_story_x`, status `CORROBORATED`).
- `canonical_event_sources`: Exactly 2 rows with foreign keys referencing `evt_5ef_story_x`.
- `canonical_source_health`: Source 1 and Source 2 are `HEALTHY`, Source 3 is `DEGRADED`.

### Stage 4: Production FastAPI Delivery & Lifespan Verification (Process Context C)
FastAPI application boots via lifespan:
- `GET /v1/articles`: Returns 2 articles (`total = 2`).
- `GET /v1/articles?source=techcrunch`: Returns 1 article.
- `GET /v1/articles/art_5ef_tc` and `GET /v1/articles/art_5ef_verge`: Both return 200 OK.
- `GET /v1/events`: Returns 1 unified TechEvent with `sources = 2`.
- `GET /v1/events/evt_5ef_story_x`: Returns full details and timeline.
- `GET /v1/events/stream`: Real-time SSE stream subscriber verifies publication event delivery.

---

## 4. WAL Concurrency & High-Throughput Stress Test

The integration test will simulate real-world production concurrency:
- **Writers:**
  - Concurrent pipeline tasks ingesting distinct articles and events.
  - Concurrent swarm supervisor tasks updating source health.
- **Readers:**
  - Concurrent FastAPI client threads querying `/v1/articles`, `/v1/events`, and `/v1/events/{id}`.
- **Verification Invariants:**
  - Zero `sqlite3.OperationalError: database is locked`.
  - Zero corrupted JSON payloads.
  - Zero missing rows or orphaned foreign keys.

---

## 5. Architectural Boundary & Dependency Inversion Purity

```text
                  CANONICAL MEMORY (SQLite)
                             ▲
                             │
                    Shared SqliteEngine
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ArticleRepository EventRepository HealthRepository
              ▲              ▲              ▲
              │              │              │
       (Protocols)    (Protocols)    (Protocols)
              │              │              │
       ┌──────┴──────┐       │       ┌──────┴──────┐
       ▼             ▼       ▼       ▼             ▼
   Pipeline S06     FastAPI Routes  Pipeline S10  ZombieSwarm
```

### Invariant:
- `src/pipeline/` contains zero SQLite imports.
- `src/zombies/` contains zero SQLite imports.
- `src/api/routes/articles.py` and `src/api/routes/events.py` contain zero SQLite imports.
- All three layers communicate through their respective protocol boundaries.

---

## 6. Scope & Target Files

### Files to Add:
1. `tests/test_phase5e_f_integration.py` (New comprehensive integration test file)
2. `PHASE_5E_F_ARCHITECTURE_REVIEW.md` (This document)
3. `PHASE_5E_F_IMPLEMENTATION_REPORT.md` (Closeout documentation)

### Files Explicitly FORBIDDEN from Modification:
- `src/domain/*`
- `src/storage/*`
- `src/pipeline/*`
- `src/zombies/*`
- `src/api/*`
- `src/database.py`, `src/db_storage/`, `src/events/`

---

## 7. Acceptance Criteria for Subphase 5E-F

1. **Full Multi-Lifecycle Continuity:** 4-stage cold restart experiment completes with 100% data and state integrity.
2. **Corroboration Across Restart:** Pre-restart event is hydrated in S07 and correctly corroborated by post-restart observation.
3. **Swarm Health Continuity:** Cooldowns and degradation survive restart and govern subsequent hunting pacing.
4. **FastAPI Delivery Fidelity:** Both articles and events are fully accessible via REST and SSE endpoints.
5. **WAL Concurrency Stability:** Multi-reader multi-writer stress test executes without SQLite lock errors.
6. **AST Boundary Purity:** Zero forbidden imports across pipeline, zombies, and API route layers.
7. **Regression Baseline:** All 334 existing tests + all new 5E-F tests pass (100% passing).

---

**Architecture Review Complete.** Ready to proceed with Subphase 5E-F implementation upon your approval.
